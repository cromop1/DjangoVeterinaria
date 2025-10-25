import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from itertools import chain

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.db.models import Count, F, Q, Sum, Max
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .forms import FarmacoForm, ProductoForm, VacunaRegistroForm
from .models import (
    Cita,
    CitaFarmaco,
    Farmaco,
    HistorialMedico,
    Paciente,
    Producto,
    Propietario,
    Sucursal,
    User,
    VacunaRecomendada,
    VacunaRegistro,
)


def _producto_table_available() -> bool:
    """Return True if the Producto table exists in the configured database."""

    table_name = Producto._meta.db_table
    try:
        return table_name in connection.introspection.table_names()
    except (OperationalError, ProgrammingError):
        return False


def _vacunas_tables_available() -> bool:
    required_tables = {
        VacunaRecomendada._meta.db_table,
        VacunaRegistro._meta.db_table,
    }
    try:
        tables = set(connection.introspection.table_names())
    except (OperationalError, ProgrammingError):
        return False
    return required_tables.issubset(tables)


def _normalizar_especie_mascota(especie: str) -> str:
    valor = (especie or "").strip().lower()
    if valor.startswith("perr") or valor.startswith("can"):
        return "canino"
    if valor.startswith("gat") or valor.startswith("fel"):
        return "felino"
    return ""


def _solo_digitos_telefono(telefono: str) -> str:
    return "".join(ch for ch in (telefono or "") if ch.isdigit())


def _roles_con_sucursal():
    return {"ADMIN", "ADMIN_OP", "VET"}


def _filtrar_por_sucursal(queryset, user, field_name="sucursal"):
    if getattr(user, "is_superuser", False):
        return queryset
    if getattr(user, "rol", None) not in _roles_con_sucursal():
        return queryset
    sucursal_id = getattr(user, "sucursal_id", None)
    if not sucursal_id:
        return queryset.none()
    return queryset.filter(**{f"{field_name}_id": sucursal_id})


def _usuario_puede_gestionar_sucursal(user, sucursal_id):
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "rol", None) not in _roles_con_sucursal():
        return False
    return sucursal_id is not None and sucursal_id == getattr(user, "sucursal_id", None)


def _sucursales_para_usuario(user):
    if getattr(user, "is_superuser", False):
        return Sucursal.objects.all()
    sucursal_id = getattr(user, "sucursal_id", None)
    if sucursal_id:
        return Sucursal.objects.filter(id=sucursal_id)
    return Sucursal.objects.none()


def _veterinarios_activos(sucursal=None):
    queryset = User.objects.filter(rol="VET", activo=True, is_active=True)
    if sucursal is not None:
        queryset = queryset.filter(sucursal=sucursal)
    return queryset.order_by("first_name", "last_name", "username")


def _inventario_por_sucursal(sucursal):
    if sucursal is None:
        return {
            "farmacos": [],
            "resumen": {
                "total_items": 0,
                "total_stock": 0,
                "ultima_actualizacion": None,
                "categorias": [],
                "criticos": [],
            },
        }

    inventario_qs = (
        Farmaco.objects.filter(sucursal=sucursal)
        .order_by("categoria", "nombre")
        .select_related("sucursal")
    )
    farmacos = list(inventario_qs)

    ultima_actualizacion = None
    if farmacos:
        ultima_actualizacion = max(
            (farmaco.actualizado for farmaco in farmacos), default=None
        )

    categorias = []
    for valor, etiqueta in Farmaco.Categoria.choices:
        elementos = [farmaco for farmaco in farmacos if farmaco.categoria == valor]
        if elementos:
            categorias.append(
                {
                    "codigo": valor,
                    "nombre": etiqueta,
                    "total_items": len(elementos),
                    "total_stock": sum(farmaco.stock for farmaco in elementos),
                    "items": elementos,
                }
            )

    criticos = [farmaco for farmaco in farmacos if farmaco.stock <= 5]

    return {
        "farmacos": farmacos,
        "resumen": {
            "total_items": len(farmacos),
            "total_stock": sum(farmaco.stock for farmaco in farmacos),
            "ultima_actualizacion": ultima_actualizacion,
            "categorias": categorias,
            "criticos": criticos,
        },
    }


def _format_excel_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return str(value)


def _excel_sections_response(filename, sections):
    parts = [
        "<html><head><meta charset='utf-8'></head>",
        "<body style='font-family:Arial,Helvetica,sans-serif;font-size:13px;'>",
    ]

    for section in sections:
        title = section.get("title")
        description = section.get("description")
        headers = section.get("headers", [])
        rows = section.get("rows", [])

        if title:
            parts.append(
                f"<h2 style='color:#0f172a;margin-bottom:0.35rem;'>{escape(title)}</h2>"
            )
        if description:
            parts.append(
                f"<p style='margin-top:0;margin-bottom:0.8rem;color:#334155;'>{escape(description)}</p>"
            )

        parts.append(
            "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;margin-bottom:1.5rem;width:100%;'>"
        )

        if headers:
            parts.append("<thead><tr>")
            for header in headers:
                parts.append(
                    f"<th style='background-color:#0f172a;color:#ffffff;text-align:left;'>{escape(header)}</th>"
                )
            parts.append("</tr></thead>")

        parts.append("<tbody>")
        if rows:
            for row in rows:
                parts.append("<tr>")
                for value in row:
                    text = _format_excel_value(value)
                    escaped = escape(text).replace("\n", "<br>")
                    parts.append(f"<td>{escaped}</td>")
                parts.append("</tr>")
        else:
            colspan = max(len(headers), 1)
            parts.append(
                f"<tr><td colspan='{colspan}' style='text-align:center;color:#64748b;'>Sin registros disponibles</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</body></html>")

    response = HttpResponse(content_type="application/vnd.ms-excel")
    response["Content-Disposition"] = f"attachment; filename={filename}"
    response.write("".join(parts))
    return response


# ----------------------------
# Sitio público
# ----------------------------

def landing(request):
    productos_destacados = Producto.objects.none()
    total_productos = 0
    productos_disponibles = _producto_table_available()

    if productos_disponibles:
        productos_destacados = Producto.objects.filter(disponible=True)[:6]
        total_productos = Producto.objects.filter(disponible=True).count()

    citas_programadas = Cita.objects.filter(estado="programada").exclude(
        fecha_hora__isnull=True
    )
    cita_proxima = (
        citas_programadas.filter(fecha_hora__gte=timezone.now())
        .order_by("fecha_hora")
        .select_related("paciente", "veterinario", "paciente__propietario__user")
        .first()
    )

    nombre_veterinario = ""
    nombre_propietario = ""
    if cita_proxima:
        if cita_proxima.veterinario:
            nombre_veterinario = (
                cita_proxima.veterinario.get_full_name()
                or cita_proxima.veterinario.username
            )
        propietario_user = cita_proxima.paciente.propietario.user
        nombre_propietario = propietario_user.get_full_name() or propietario_user.username

    context = {
        "productos_destacados": productos_destacados,
        "total_productos": total_productos,
        "total_propietarios": Propietario.objects.count(),
        "total_pacientes": Paciente.objects.count(),
        "total_veterinarios": User.objects.filter(rol="VET").count(),
        "total_citas_programadas": citas_programadas.count(),
        "cita_proxima": cita_proxima,
        "cita_proxima_veterinario": nombre_veterinario,
        "cita_proxima_propietario": nombre_propietario,
    }

    return render(
        request,
        "core/landing.html",
        context,
    )


def contacto(request):
    """Página de contacto institucional de la veterinaria."""

    sucursales = Sucursal.objects.all()
    sucursal_principal = sucursales.first()

    telefono_base = "+54 351 530-1903"
    telefono_principal = telefono_base
    direccion_principal = "Juan Perrin 6089, Córdoba, Argentina"
    if sucursal_principal:
        direccion_principal = sucursal_principal.direccion
        if sucursal_principal.ciudad:
            direccion_principal = f"{direccion_principal}, {sucursal_principal.ciudad}"
        if sucursal_principal.telefono:
            telefono_principal = sucursal_principal.telefono

    telefono_normalizado = _solo_digitos_telefono(telefono_principal) or "543515301903"

    sucursales_info = []
    for sucursal in sucursales:
        telefono_sucursal = sucursal.telefono or ""
        telefono_sucursal_normalizado = _solo_digitos_telefono(telefono_sucursal)
        sucursales_info.append(
            {
                "sucursal": sucursal,
                "telefono_link": (
                    f"tel:+{telefono_sucursal_normalizado}"
                    if telefono_sucursal_normalizado
                    else ""
                ),
                "whatsapp_url": (
                    f"https://wa.me/{telefono_sucursal_normalizado}"
                    if telefono_sucursal_normalizado
                    else ""
                ),
            }
        )

    context = {
        "titulo_pagina": "Contacto",
        "direccion": direccion_principal,
        "telefono": telefono_principal,
        "telefono_link": f"tel:+{telefono_normalizado}",
        "email": "contacto@sabuesofeliz.com",
        "horarios": {
            "Lunes a Viernes": "08:00 a 20:00",
            "Sábados": "09:00 a 14:00",
        },
        "whatsapp_url": f"https://wa.me/{telefono_normalizado}",
        "sucursales_info": sucursales_info,
    }

    return render(request, "core/contacto.html", context)


def tienda(request):
    categoria = request.GET.get("categoria")
    busqueda = request.GET.get("q", "").strip()

    productos = Producto.objects.none()

    productos_disponibles = _producto_table_available()

    if productos_disponibles:
        productos = Producto.objects.filter(disponible=True)
        if categoria in dict(Producto.CATEGORIAS):
            productos = productos.filter(categoria=categoria)
        if busqueda:
            productos = productos.filter(
                Q(nombre__icontains=busqueda) | Q(descripcion__icontains=busqueda)
            )

        productos = productos.order_by("nombre")

    return render(
        request,
        "core/tienda.html",
        {
            "productos": productos,
            "categoria_activa": categoria,
            "busqueda": busqueda,
            "categorias": Producto.CATEGORIAS,
        },
    )


def detalle_producto(request, producto_id):
    if not _producto_table_available():
        messages.error(
            request,
            "La tienda aún no está configurada. Ejecuta las migraciones pendientes para administrar productos.",
        )
        return redirect("landing")

    queryset = Producto.objects.filter(disponible=True)
    if request.user.is_authenticated and request.user.rol == "ADMIN":
        queryset = Producto.objects.all()
    producto = get_object_or_404(queryset, id=producto_id)
    relacionados = (
        Producto.objects.filter(disponible=True, categoria=producto.categoria)
        .exclude(id=producto.id)
        .order_by("-actualizado")[:4]
    )
    return render(
        request,
        "core/detalle_producto.html",
        {"producto": producto, "relacionados": relacionados},
    )


# ----------------------------
# Dashboard y estadísticas
# ----------------------------


@login_required
def dashboard(request):
    user = request.user
    context = {}

    if user.rol == "ADMIN":
        if not user.is_superuser and not getattr(user, "sucursal_id", None):
            messages.warning(
                request,
                "Asigna una sucursal a tu perfil para comenzar a gestionar la operación.",
            )

        usuarios_qs = _filtrar_por_sucursal(User.objects.all(), user)
        pacientes_qs = Paciente.objects.all()
        if not user.is_superuser:
            pacientes_qs = pacientes_qs.filter(
                cita__sucursal_id=user.sucursal_id
            ).distinct()
        citas_qs = _filtrar_por_sucursal(Cita.objects.all(), user)
        historiales_qs = HistorialMedico.objects.all()
        if not user.is_superuser:
            historiales_qs = historiales_qs.filter(
                paciente__cita__sucursal_id=user.sucursal_id
            ).distinct()

        context["total_usuarios"] = usuarios_qs.count()
        context["total_pacientes"] = pacientes_qs.count()
        context["total_citas"] = citas_qs.count()
        context["total_historiales"] = historiales_qs.count()
        productos_disponibles = _producto_table_available()
        context["total_productos"] = Producto.objects.count() if productos_disponibles else 0
        resumen = {estado: 0 for estado, _ in Cita.ESTADOS}
        for item in citas_qs.values("estado").annotate(total=Count("id")):
            resumen[item["estado"]] = item["total"]
        context["resumen_citas"] = resumen
        context["todas_citas"] = (
            citas_qs.select_related(
                "paciente",
                "paciente__propietario__user",
                "veterinario",
                "historial_medico",
            )
            .order_by("-fecha_solicitada", "-fecha_hora")[:20]
        )
        context["todos_pacientes"] = (
            pacientes_qs.select_related("propietario__user").order_by("nombre")[:20]
        )
        context["productos_recientes"] = (
            Producto.objects.order_by("-actualizado")[:6]
            if productos_disponibles
            else Producto.objects.none()
        )
    elif user.rol == "VET":
        mi_sucursal = getattr(user, "sucursal", None)
        if mi_sucursal is None:
            messages.warning(
                request,
                "Tu perfil aún no tiene una sucursal asignada. Comunícate con un administrador para actualizar tus datos.",
            )
        context["mis_citas"] = (
            Cita.objects.filter(veterinario=user)
            .select_related(
                "paciente", "paciente__propietario__user", "historial_medico"
            )
            .order_by("-fecha_hora", "-fecha_solicitada")
        )
        context["mis_historiales"] = HistorialMedico.objects.filter(
            veterinario=user
        ).order_by("-fecha")
        context["mi_sucursal"] = mi_sucursal
        if mi_sucursal is not None:
            inventario = _inventario_por_sucursal(mi_sucursal)
            context["inventario_veterinario"] = inventario["resumen"]
        else:
            context["inventario_veterinario"] = None
    elif user.rol == "OWNER":
        productos_disponibles = _producto_table_available()
        propietario = (
            Propietario.objects.select_related("user")
            .filter(user=user)
            .first()
        )

        if propietario is None:
            messages.warning(
                request,
                "Tu perfil de propietario aún no está completo. Solicita al equipo administrativo que registre tus datos para acceder a todas las funciones.",
            )
            context.update(
                {
                    "propietario_incompleto": True,
                    "mis_mascotas": [],
                    "mis_citas": [],
                    "mis_historiales": [],
                    "proxima_cita": None,
                    "citas_proximas": [],
                    "citas_recientes": [],
                    "citas_pendientes": [],
                    "historiales_recientes": [],
                    "estadisticas_propietario": {
                        "mascotas": 0,
                        "citas_activas": 0,
                        "informes": 0,
                        "profesionales": 0,
                    },
                }
            )
        else:
            mascotas = list(
                Paciente.objects.filter(propietario=propietario).order_by("nombre")
            )
            citas_queryset = (
                Cita.objects.filter(paciente__propietario=propietario)
                .select_related("paciente", "veterinario")
                .order_by("-fecha_solicitada", "-fecha_hora")
            )
            citas = list(citas_queryset)
            historiales_queryset = (
                HistorialMedico.objects.filter(paciente__propietario=propietario)
                .select_related("paciente", "veterinario")
                .order_by("-fecha")
            )
            historiales = list(historiales_queryset)

            ahora = timezone.now()
            citas_confirmadas = [c for c in citas if c.fecha_hora]
            citas_confirmadas.sort(key=lambda cita: cita.fecha_hora)
            citas_proximas = [c for c in citas_confirmadas if c.fecha_hora >= ahora]
            citas_pasadas = [c for c in citas_confirmadas if c.fecha_hora < ahora]
            citas_pasadas.sort(key=lambda cita: cita.fecha_hora, reverse=True)
            citas_pendientes = [c for c in citas if not c.fecha_hora]

            context.update(
                {
                    "mis_mascotas": mascotas,
                    "mis_citas": citas,
                    "mis_historiales": historiales,
                    "proxima_cita": citas_proximas[0] if citas_proximas else None,
                    "citas_proximas": citas_proximas[:5],
                    "citas_recientes": citas_pasadas[:5],
                    "citas_pendientes": citas_pendientes,
                    "historiales_recientes": historiales[:5],
                    "estadisticas_propietario": {
                        "mascotas": len(mascotas),
                        "citas_activas": len(citas_proximas)
                        + len(citas_pendientes),
                        "informes": len(historiales),
                        "profesionales": len(
                            {c.veterinario_id for c in citas if c.veterinario_id}
                        ),
                    },
                }
            )

        context["productos_sugeridos"] = (
            Producto.objects.filter(disponible=True)
            .order_by("-actualizado")[:3]
            if productos_disponibles
            else Producto.objects.none()
        )
    elif user.rol == "ADMIN_OP":
        if not user.is_superuser and not getattr(user, "sucursal_id", None):
            messages.warning(
                request,
                "Asigna una sucursal a tu perfil para comenzar a gestionar la operación.",
            )

        context["todas_citas"] = _filtrar_por_sucursal(
            Cita.objects.select_related(
                "paciente",
                "paciente__propietario__user",
                "veterinario",
            ).order_by("-fecha_solicitada", "-fecha_hora"),
            user,
        )
        context["todos_pacientes"] = _filtrar_por_sucursal(
            Paciente.objects.select_related("propietario__user").order_by("nombre"),
            user,
            field_name="cita__sucursal",
        ).distinct()

    return render(request, "core/dashboard.html", context)


@login_required
def dashboard_admin_analisis(request):
    usuario = request.user
    if not (usuario.is_superuser or usuario.rol == "ADMIN"):
        messages.error(
            request,
            "Acceso restringido. Solo los administradores pueden consultar el módulo de análisis.",
        )
        return redirect("dashboard")

    sucursales_qs = _sucursales_para_usuario(usuario)
    sucursales = list(sucursales_qs)
    sucursal_param = request.GET.get("sucursal", "")
    mostrar_opcion_todas = usuario.is_superuser and len(sucursales) > 1
    sucursal_seleccionada = None

    if usuario.is_superuser:
        if sucursal_param and sucursal_param not in {"", "todas"}:
            sucursal_seleccionada = next(
                (s for s in sucursales if str(s.id) == sucursal_param),
                None,
            )
            if sucursal_seleccionada is None:
                messages.error(request, "La sucursal seleccionada no es válida.")
                return redirect("dashboard_admin_analisis")
        elif not sucursal_param:
            if len(sucursales) == 1:
                sucursal_seleccionada = sucursales[0]
                sucursal_param = str(sucursal_seleccionada.id)
            elif mostrar_opcion_todas:
                sucursal_param = "todas"
    else:
        sucursal_seleccionada = getattr(usuario, "sucursal", None)
        if sucursal_seleccionada is not None:
            sucursal_param = str(sucursal_seleccionada.id)

    citas_base = _filtrar_por_sucursal(
        Cita.objects.select_related(
            "paciente",
            "paciente__propietario__user",
            "veterinario",
            "sucursal",
        ).order_by("-fecha_hora", "-fecha_solicitada"),
        usuario,
    )
    if sucursal_seleccionada is not None:
        citas_base = citas_base.filter(sucursal=sucursal_seleccionada)

    farmacos_qs = _filtrar_por_sucursal(
        Farmaco.objects.select_related("sucursal"),
        usuario,
    )
    if sucursal_seleccionada is not None:
        farmacos_qs = farmacos_qs.filter(sucursal=sucursal_seleccionada)

    farmacos_utilizados_qs = _filtrar_por_sucursal(
        CitaFarmaco.objects.select_related(
            "cita__paciente__propietario__user",
            "cita__veterinario",
            "cita__sucursal",
            "farmaco",
        ),
        usuario,
        field_name="cita__sucursal",
    )
    if sucursal_seleccionada is not None:
        farmacos_utilizados_qs = farmacos_utilizados_qs.filter(
            cita__sucursal=sucursal_seleccionada
        )

    periodos_inventario = {
        "dia": {"label": "Últimas 24 horas", "dias": 1},
        "semana": {"label": "Últimos 7 días", "dias": 7},
        "mes": {"label": "Últimos 30 días", "dias": 30},
    }
    inventario_periodo = request.GET.get("inventario_periodo", "mes")
    if inventario_periodo not in periodos_inventario:
        inventario_periodo = "mes"
    inventario_periodo_info = periodos_inventario[inventario_periodo]
    inicio_periodo_inventario = timezone.now() - timedelta(
        days=inventario_periodo_info["dias"]
    )

    farmacos_periodo_qs = farmacos_utilizados_qs.filter(
        registrado__gte=inicio_periodo_inventario
    )

    total_farmacos_utilizados = (
        farmacos_periodo_qs.aggregate(total=Sum("cantidad")).get("total") or 0
    )

    categoria_labels = []
    categoria_data = []
    categoria_lookup = dict(Farmaco.Categoria.choices)
    for registro in (
        farmacos_periodo_qs.values("farmaco__categoria")
        .annotate(total=Sum("cantidad"))
        .order_by("-total")
    ):
        categoria = registro["farmaco__categoria"]
        etiqueta = categoria_lookup.get(categoria, categoria or "Sin categoría")
        categoria_labels.append(etiqueta)
        categoria_data.append(registro["total"])

    top_farmacos = []
    for registro in (
        farmacos_periodo_qs.values(
            "farmaco__id",
            "farmaco__nombre",
            "farmaco__categoria",
            "farmaco__sucursal__nombre",
        )
        .annotate(
            total=Sum("cantidad"),
            pacientes=Count("cita__paciente", distinct=True),
        )
        .order_by("-total")[:8]
    ):
        categoria = registro["farmaco__categoria"]
        top_farmacos.append(
            {
                "nombre": registro["farmaco__nombre"],
                "categoria": categoria_lookup.get(
                    categoria, categoria or "Sin categoría"
                ),
                "total": registro["total"],
                "pacientes": registro["pacientes"],
                "sucursal": registro["farmaco__sucursal__nombre"],
            }
        )

    propietarios_qs = Propietario.objects.select_related("user")
    propietarios_qs = propietarios_qs.order_by(
        "user__first_name", "user__last_name", "user__username"
    )
    if sucursal_seleccionada is not None:
        propietarios_qs = propietarios_qs.filter(
            paciente__cita__sucursal=sucursal_seleccionada
        ).distinct()
    elif not usuario.is_superuser and getattr(usuario, "sucursal_id", None):
        propietarios_qs = propietarios_qs.filter(
            paciente__cita__sucursal_id=usuario.sucursal_id
        ).distinct()

    propietarios_farmacos = list(
        farmacos_qs.order_by("nombre").values("id", "nombre")[:150]
    )

    expediente_periodos = {
        "todo": {"label": "Todo el historial", "dias": None},
        "30": {"label": "Últimos 30 días", "dias": 30},
        "90": {"label": "Últimos 90 días", "dias": 90},
        "365": {"label": "Últimos 12 meses", "dias": 365},
    }
    expediente_periodo = request.GET.get("expediente_periodo", "todo")
    if expediente_periodo not in expediente_periodos:
        expediente_periodo = "todo"

    propietario_q = (request.GET.get("propietario_q") or "").strip()
    propietario_farmaco = request.GET.get("propietario_farmaco", "").strip()

    if propietario_q:
        propietarios_qs = propietarios_qs.filter(
            Q(user__first_name__icontains=propietario_q)
            | Q(user__last_name__icontains=propietario_q)
            | Q(user__username__icontains=propietario_q)
            | Q(user__email__icontains=propietario_q)
            | Q(telefono__icontains=propietario_q)
            | Q(paciente__nombre__icontains=propietario_q)
        ).distinct()

    dias_periodo_expediente = expediente_periodos[expediente_periodo]["dias"]
    if dias_periodo_expediente:
        inicio_expediente = timezone.now() - timedelta(days=dias_periodo_expediente)
        propietarios_qs = propietarios_qs.filter(
            Q(paciente__cita__fecha_solicitada__gte=inicio_expediente)
            | Q(paciente__cita__fecha_hora__gte=inicio_expediente)
        ).distinct()

    if propietario_farmaco.isdigit():
        propietarios_qs = propietarios_qs.filter(
            paciente__cita__administraciones_farmacos__farmaco_id=int(propietario_farmaco)
        ).distinct()

    total_propietarios = propietarios_qs.count()
    propietarios_para_descarga = list(propietarios_qs[:25])

    rendimiento_veterinarios = []
    for registro in (
        citas_base.filter(estado="atendida", veterinario__isnull=False)
        .values(
            "veterinario__id",
            "veterinario__first_name",
            "veterinario__last_name",
            "veterinario__username",
            "veterinario__sucursal__nombre",
        )
        .annotate(
            total=Count("id"),
            pacientes=Count("paciente", distinct=True),
            farmacos=Sum("administraciones_farmacos__cantidad"),
        )
        .order_by("-total")[:6]
    ):
        nombre = registro["veterinario__first_name"] or ""
        apellido = registro["veterinario__last_name"] or ""
        username = registro["veterinario__username"] or ""
        nombre_visible = (f"{nombre} {apellido}" or username).strip()
        if not nombre_visible:
            nombre_visible = username
        rendimiento_veterinarios.append(
            {
                "nombre": nombre_visible,
                "sucursal": registro["veterinario__sucursal__nombre"],
                "total": registro["total"],
                "pacientes": registro["pacientes"],
                "farmacos": registro["farmacos"] or 0,
            }
        )

    propietarios_inventario_periodo = (
        farmacos_periodo_qs.values("cita__paciente__propietario_id")
        .exclude(cita__paciente__propietario_id__isnull=True)
        .distinct()
        .count()
    )
    veterinarios_inventario_periodo = (
        farmacos_periodo_qs.values("cita__veterinario_id")
        .exclude(cita__veterinario_id__isnull=True)
        .distinct()
        .count()
    )

    resumen_inventario_periodo = {
        "dispensaciones": total_farmacos_utilizados,
        "propietarios": propietarios_inventario_periodo,
        "veterinarios": veterinarios_inventario_periodo,
    }

    categorias_destacadas = [
        {"nombre": categoria_labels[idx], "total": categoria_data[idx]}
        for idx in range(len(categoria_labels))
    ][:6]

    momento_actual = timezone.localtime(timezone.now())

    if sucursal_seleccionada is not None:
        export_sucursal_param = str(sucursal_seleccionada.id)
    elif usuario.is_superuser and (sucursal_param == "todas" or not sucursal_param):
        export_sucursal_param = "todas"
    else:
        export_sucursal_param = ""

    context = {
        "sucursales": sucursales,
        "sucursal_seleccionada": sucursal_seleccionada,
        "sucursal_param": sucursal_param,
        "mostrar_opcion_todas": mostrar_opcion_todas,
        "top_farmacos": top_farmacos,
        "categorias_destacadas": categorias_destacadas,
        "propietarios_para_descarga": propietarios_para_descarga,
        "propietarios_total": total_propietarios,
        "rendimiento_veterinarios": rendimiento_veterinarios,
        "momento_actual": momento_actual,
        "grafico_categorias_labels": json.dumps(categoria_labels),
        "grafico_categorias_data": json.dumps(categoria_data),
        "export_sucursal_param": export_sucursal_param,
        "inventario_periodo": inventario_periodo,
        "inventario_periodos": periodos_inventario,
        "inventario_periodo_label": inventario_periodo_info["label"],
        "resumen_inventario_periodo": resumen_inventario_periodo,
        "expediente_periodo": expediente_periodo,
        "expediente_periodos": expediente_periodos,
        "propietario_q": propietario_q,
        "propietario_farmaco": propietario_farmaco,
        "propietarios_farmacos": propietarios_farmacos,
    }

    return render(request, "core/dashboard_admin_analisis.html", context)


# ----------------------------
# Descargas de reportes
# ----------------------------


@login_required
def exportar_inventario_excel(request):
    usuario = request.user
    if not (usuario.is_superuser or usuario.rol == "ADMIN"):
        messages.error(
            request,
            "Solo los administradores pueden descargar los reportes del inventario farmacológico.",
        )
        return redirect("dashboard")

    periodo = (request.GET.get("periodo") or "semanal").lower()
    periodos_validos = {"semanal": 7, "mensual": 30}
    if periodo not in periodos_validos:
        periodo = "semanal"

    dias_intervalo = periodos_validos[periodo]
    inicio = timezone.now() - timedelta(days=dias_intervalo)
    periodo_label = {
        "semanal": "Últimos 7 días",
        "mensual": "Últimos 30 días",
    }[periodo]

    sucursal_param = request.GET.get("sucursal", "")
    sucursales_qs = _sucursales_para_usuario(usuario)
    sucursal_filtro = None
    sucursal_nombre = "Todas las sucursales"

    if sucursal_param and sucursal_param != "todas":
        if not sucursal_param.isdigit():
            messages.error(request, "La sucursal indicada no es válida.")
            return redirect("dashboard_admin_analisis")
        sucursal_id = int(sucursal_param)
        if not sucursales_qs.filter(id=sucursal_id).exists():
            messages.error(request, "No tienes permisos sobre la sucursal seleccionada.")
            return redirect("dashboard_admin_analisis")
        sucursal_filtro = sucursal_id
        sucursal_nombre = (
            Sucursal.objects.filter(id=sucursal_id).values_list("nombre", flat=True).first()
            or "Sucursal"
        )
    elif not usuario.is_superuser:
        sucursal_filtro = getattr(usuario, "sucursal_id", None)
        sucursal_nombre = (
            getattr(usuario.sucursal, "nombre", "Sucursal no asignada")
        )

    farmacos_qs = _filtrar_por_sucursal(
        CitaFarmaco.objects.select_related(
            "cita__paciente__propietario__user",
            "cita__veterinario",
            "cita__sucursal",
            "farmaco",
        ),
        usuario,
        field_name="cita__sucursal",
    )
    if sucursal_filtro is not None:
        farmacos_qs = farmacos_qs.filter(cita__sucursal_id=sucursal_filtro)

    farmacos_qs = farmacos_qs.filter(registrado__gte=inicio)

    total_registros = farmacos_qs.count()
    unidades_utilizadas = (
        farmacos_qs.aggregate(total=Sum("cantidad")).get("total") or 0
    )
    citas_incluidas = farmacos_qs.values("cita_id").distinct().count()
    pacientes_incluidos = farmacos_qs.values("cita__paciente_id").distinct().count()
    veterinarios_involucrados = farmacos_qs.filter(
        cita__veterinario__isnull=False
    ).values("cita__veterinario_id").distinct().count()

    categoria_lookup = dict(Farmaco.Categoria.choices)
    momento_actual = timezone.localtime(timezone.now())

    filas_detalle = []
    for registro in farmacos_qs.order_by("-cita__fecha_hora", "-registrado"):
        cita = registro.cita
        paciente = cita.paciente
        propietario = paciente.propietario
        propietario_user = propietario.user
        veterinario = cita.veterinario

        filas_detalle.append(
            [
                cita.sucursal.nombre if cita.sucursal_id else "",
                cita.fecha_hora or cita.fecha_solicitada,
                registro.registrado,
                cita.get_estado_display(),
                cita.get_tipo_display(),
                (veterinario.get_full_name() or veterinario.username)
                if veterinario
                else "Sin asignar",
                paciente.nombre,
                propietario_user.get_full_name() or propietario_user.username,
                propietario.telefono or propietario_user.telefono,
                propietario_user.email,
                registro.farmaco.nombre,
                categoria_lookup.get(
                    registro.farmaco.categoria, registro.farmaco.categoria
                ),
                registro.cantidad,
                registro.farmaco.stock,
                cita.notas,
            ]
        )

    resumen_contexto = {
        "title": "Contexto del informe",
        "headers": ["Indicador", "Valor"],
        "rows": [
            ["Generado", momento_actual],
            ["Periodo", periodo_label],
            ["Sucursal", sucursal_nombre],
            ["Registros analizados", total_registros],
            ["Unidades dispensadas", unidades_utilizadas],
            ["Citas impactadas", citas_incluidas],
            ["Pacientes únicos", pacientes_incluidos],
            ["Veterinarios involucrados", veterinarios_involucrados],
        ],
    }

    seccion_detalle = {
        "title": "Dispensación detallada por cita",
        "headers": [
            "Sucursal",
            "Fecha de la cita",
            "Registro",
            "Estado",
            "Tipo",
            "Veterinario",
            "Paciente",
            "Propietario",
            "Teléfono",
            "Email",
            "Fármaco",
            "Categoría",
            "Cantidad",
            "Stock actual",
            "Notas de la cita",
        ],
        "rows": filas_detalle,
    }

    filas_categorias = []
    for registro in (
        farmacos_qs.values("farmaco__categoria")
        .annotate(unidades=Sum("cantidad"), items=Count("farmaco", distinct=True))
        .order_by("-unidades")
    ):
        etiqueta = categoria_lookup.get(
            registro["farmaco__categoria"], registro["farmaco__categoria"]
        )
        filas_categorias.append(
            [
                etiqueta,
                registro["items"],
                registro["unidades"],
            ]
        )

    seccion_categorias = {
        "title": "Resumen por categoría terapéutica",
        "headers": ["Categoría", "Referencias", "Unidades dispensadas"],
        "rows": filas_categorias,
    }

    filas_farmacos = []
    for registro in (
        farmacos_qs.values("farmaco__nombre", "farmaco__categoria")
        .annotate(
            unidades=Sum("cantidad"),
            citas=Count("cita", distinct=True),
            pacientes=Count("cita__paciente", distinct=True),
            stock=Max("farmaco__stock"),
        )
        .order_by("-unidades")
    ):
        filas_farmacos.append(
            [
                registro["farmaco__nombre"],
                categoria_lookup.get(
                    registro["farmaco__categoria"], registro["farmaco__categoria"]
                ),
                registro["unidades"],
                registro["citas"],
                registro["pacientes"],
                registro["stock"],
            ]
        )

    seccion_farmacos = {
        "title": "Principales fármacos dispensados",
        "headers": [
            "Fármaco",
            "Categoría",
            "Unidades",
            "Citas",
            "Pacientes",
            "Stock actual",
        ],
        "rows": filas_farmacos,
    }

    filename = f"reporte_inventario_{periodo}_{momento_actual:%Y%m%d%H%M}.xls"
    return _excel_sections_response(
        filename,
        [resumen_contexto, seccion_detalle, seccion_categorias, seccion_farmacos],
    )


@login_required
def exportar_propietario_excel(request, propietario_id):
    usuario = request.user
    if not (usuario.is_superuser or usuario.rol == "ADMIN"):
        messages.error(
            request,
            "Solo los administradores pueden descargar expedientes completos de propietarios.",
        )
        return redirect("dashboard")

    propietario = get_object_or_404(
        Propietario.objects.select_related("user"), id=propietario_id
    )

    sucursal_param = request.GET.get("sucursal", "")
    sucursal_filtro = None
    sucursal_nombre = "Todas las sucursales"

    if usuario.is_superuser:
        if sucursal_param and sucursal_param not in {"", "todas"}:
            if not sucursal_param.isdigit():
                messages.error(request, "La sucursal indicada no es válida.")
                return redirect("dashboard_admin_analisis")
            sucursal_id = int(sucursal_param)
            sucursal = Sucursal.objects.filter(id=sucursal_id).first()
            if sucursal is None:
                messages.error(request, "La sucursal seleccionada no existe.")
                return redirect("dashboard_admin_analisis")
            sucursal_filtro = sucursal.id
            sucursal_nombre = sucursal.nombre
    else:
        sucursal_filtro = getattr(usuario, "sucursal_id", None)
        sucursal_nombre = (
            getattr(usuario.sucursal, "nombre", "Sucursal no asignada")
        )
        if sucursal_param and sucursal_param not in {str(sucursal_filtro), ""}:
            messages.error(request, "No puedes consultar expedientes de otras sucursales.")
            return redirect("dashboard_admin_analisis")

    citas_qs = Cita.objects.filter(paciente__propietario=propietario).select_related(
        "paciente",
        "paciente__propietario",
        "paciente__propietario__user",
        "veterinario",
        "sucursal",
        "historial_medico",
    )
    if sucursal_filtro is not None:
        citas_qs = citas_qs.filter(sucursal_id=sucursal_filtro)

    if not usuario.is_superuser and getattr(usuario, "sucursal_id", None):
        if not citas_qs.exists():
            messages.error(
                request,
                "No se encontraron citas del propietario dentro de tu sucursal.",
            )
            return redirect("dashboard_admin_analisis")

    pacientes_qs = Paciente.objects.filter(propietario=propietario)
    if sucursal_filtro is not None:
        pacientes_qs = pacientes_qs.filter(cita__sucursal_id=sucursal_filtro).distinct()

    historiales_qs = HistorialMedico.objects.filter(
        paciente__propietario=propietario
    ).select_related("paciente", "veterinario")
    if sucursal_filtro is not None:
        historiales_qs = historiales_qs.filter(
            Q(cita__sucursal_id=sucursal_filtro)
            | Q(
                cita__isnull=True,
                paciente__cita__sucursal_id=sucursal_filtro,
            )
        ).distinct()

    farmacos_qs = CitaFarmaco.objects.filter(
        cita__paciente__propietario=propietario
    ).select_related("farmaco", "cita", "cita__sucursal")
    if sucursal_filtro is not None:
        farmacos_qs = farmacos_qs.filter(cita__sucursal_id=sucursal_filtro)

    categoria_lookup = dict(Farmaco.Categoria.choices)
    momento_actual = timezone.localtime(timezone.now())

    resumen_propietario = {
        "title": "Ficha del propietario",
        "headers": ["Campo", "Detalle"],
        "rows": [
            [
                "Propietario",
                propietario.user.get_full_name() or propietario.user.username,
            ],
            ["Correo electrónico", propietario.user.email],
            [
                "Teléfono",
                propietario.telefono or propietario.user.telefono or "Sin informar",
            ],
            ["Dirección", propietario.direccion or "Sin registrar"],
            ["Ciudad", propietario.ciudad or "Sin registrar"],
            ["Sucursal", sucursal_nombre],
            ["Expediente generado", momento_actual],
        ],
    }

    filas_mascotas = []
    for mascota in pacientes_qs.order_by("nombre"):
        filas_mascotas.append(
            [
                mascota.nombre,
                mascota.especie,
                mascota.raza or "-",
                mascota.sexo,
                mascota.fecha_nacimiento,
                mascota.vacunas or "Sin registros",
                mascota.alergias or "Sin registros",
            ]
        )

    seccion_mascotas = {
        "title": "Mascotas registradas",
        "headers": [
            "Nombre",
            "Especie",
            "Raza",
            "Sexo",
            "Fecha de nacimiento",
            "Vacunas",
            "Alergias",
        ],
        "rows": filas_mascotas,
    }

    farmacos_por_cita = defaultdict(list)
    for administracion in farmacos_qs:
        farmacos_por_cita[administracion.cita_id].append(
            f"{administracion.farmaco.nombre} (x{administracion.cantidad})"
        )

    citas_list = list(citas_qs.order_by("-fecha_hora", "-fecha_solicitada"))
    filas_citas = []
    for cita in citas_list:
        veterinario = cita.veterinario
        historial = getattr(cita, "historial_medico", None)
        farmacos_list = farmacos_por_cita.get(cita.id, [])
        filas_citas.append(
            [
                cita.fecha_hora or cita.fecha_solicitada,
                cita.get_estado_display(),
                cita.get_tipo_display(),
                cita.sucursal.nombre if cita.sucursal_id else "",
                (veterinario.get_full_name() or veterinario.username)
                if veterinario
                else "Sin asignar",
                cita.paciente.nombre,
                ", ".join(farmacos_list) if farmacos_list else "Sin registros",
                historial.diagnostico if historial else "-",
                historial.tratamiento if historial else "-",
            ]
        )

    seccion_citas = {
        "title": "Citas y atenciones",
        "headers": [
            "Fecha",
            "Estado",
            "Tipo",
            "Sucursal",
            "Veterinario",
            "Paciente",
            "Fármacos utilizados",
            "Diagnóstico",
            "Tratamiento",
        ],
        "rows": filas_citas,
    }

    filas_historial = []
    for historial in historiales_qs.order_by("-fecha"):
        veterinario = historial.veterinario
        filas_historial.append(
            [
                historial.fecha,
                historial.paciente.nombre,
                (veterinario.get_full_name() or veterinario.username)
                if veterinario
                else "Sin asignar",
                historial.diagnostico,
                historial.tratamiento,
                historial.notas or "-",
            ]
        )

    seccion_historial = {
        "title": "Historial clínico",
        "headers": [
            "Fecha",
            "Paciente",
            "Profesional",
            "Diagnóstico",
            "Tratamiento",
            "Notas",
        ],
        "rows": filas_historial,
    }

    filas_farmacos = []
    for registro in (
        farmacos_qs.values("farmaco__nombre", "farmaco__categoria")
        .annotate(
            unidades=Sum("cantidad"),
            citas=Count("cita", distinct=True),
        )
        .order_by("-unidades")
    ):
        filas_farmacos.append(
            [
                registro["farmaco__nombre"],
                categoria_lookup.get(
                    registro["farmaco__categoria"], registro["farmaco__categoria"]
                ),
                registro["unidades"],
                registro["citas"],
            ]
        )

    seccion_farmacos = {
        "title": "Fármacos administrados al propietario",
        "headers": ["Fármaco", "Categoría", "Unidades", "Citas"],
        "rows": filas_farmacos,
    }

    owner_slug = (propietario.user.username or "propietario").replace(" ", "_")
    filename = f"expediente_{owner_slug}_{momento_actual:%Y%m%d%H%M}.xls"

    secciones = [
        resumen_propietario,
        seccion_mascotas,
        seccion_citas,
        seccion_historial,
        seccion_farmacos,
    ]

    return _excel_sections_response(filename, secciones)


# ----------------------------
# Mascotas y propietarios
# ----------------------------
# Mascotas y propietarios
# ----------------------------


@login_required
def calendario_vacunas(request):
    if request.user.rol != "OWNER":
        messages.error(request, "Acceso exclusivo para propietarios.")
        return redirect("dashboard")

    propietario = get_object_or_404(Propietario, user=request.user)
    mascotas = list(
        Paciente.objects.filter(propietario=propietario).order_by("nombre")
    )

    vacunas_disponibles = _vacunas_tables_available()
    mascota_seleccionada = None
    mascota_id = request.POST.get("paciente_id") or request.GET.get("paciente")

    if mascotas:
        try:
            mascota_id_int = int(mascota_id) if mascota_id else None
        except (TypeError, ValueError):
            mascota_id_int = None

        for mascota in mascotas:
            if mascota_id_int is not None and mascota.id == mascota_id_int:
                mascota_seleccionada = mascota
                break
        if mascota_seleccionada is None:
            mascota_seleccionada = mascotas[0]
            mascota_id_int = mascota_seleccionada.id
    else:
        mascota_id_int = None

    if request.method == "POST":
        if not mascotas:
            messages.error(
                request,
                "Registra una mascota para comenzar a gestionar su calendario de vacunas.",
            )
            return redirect("registrar_mascota")

        if not vacunas_disponibles:
            messages.error(
                request,
                "El módulo de vacunas todavía no está disponible. Ejecuta las migraciones pendientes para activarlo.",
            )
            return redirect("calendario_vacunas")

        form = VacunaRegistroForm(request.POST)
        accion = request.POST.get("accion")
        redirect_base = reverse("calendario_vacunas")
        redirect_actual = (
            f"{redirect_base}?paciente={mascota_seleccionada.id}"
            if mascota_seleccionada
            else redirect_base
        )

        if form.is_valid():
            paciente_id = form.cleaned_data["paciente_id"]
            vacuna_id = form.cleaned_data["vacuna_id"]
            fecha = form.cleaned_data.get("fecha_aplicacion") or timezone.localdate()
            notas = form.cleaned_data.get("notas", "").strip()

            paciente_obj = next(
                (m for m in mascotas if m.id == paciente_id),
                None,
            )
            if paciente_obj is None:
                messages.error(request, "La mascota seleccionada no es válida.")
                return redirect(redirect_actual)

            redirect_url = f"{redirect_base}?paciente={paciente_obj.id}"

            vacuna_obj = VacunaRecomendada.objects.filter(id=vacuna_id).first()
            if vacuna_obj is None:
                messages.error(request, "La vacuna indicada no existe.")
                return redirect(redirect_url)

            especie_paciente = _normalizar_especie_mascota(paciente_obj.especie)
            if not especie_paciente:
                messages.error(
                    request,
                    "La especie de la mascota no cuenta con un calendario configurado.",
                )
                return redirect(redirect_url)

            if vacuna_obj.especie != especie_paciente:
                messages.error(
                    request,
                    "La vacuna seleccionada no corresponde a la especie de la mascota.",
                )
                return redirect(redirect_url)

            if accion == "marcar":
                registro, creado = VacunaRegistro.objects.update_or_create(
                    paciente=paciente_obj,
                    vacuna=vacuna_obj,
                    defaults={
                        "fecha_aplicacion": fecha,
                        "notas": notas,
                    },
                )
                if creado:
                    messages.success(
                        request,
                        f"Se registró la aplicación de {vacuna_obj.nombre} para {paciente_obj.nombre}.",
                    )
                else:
                    messages.success(
                        request,
                        f"Se actualizó la aplicación de {vacuna_obj.nombre} para {paciente_obj.nombre}.",
                    )
            elif accion == "desmarcar":
                eliminados, _ = VacunaRegistro.objects.filter(
                    paciente=paciente_obj, vacuna=vacuna_obj
                ).delete()
                if eliminados:
                    messages.info(
                        request,
                        f"Se eliminó el registro de {vacuna_obj.nombre} para {paciente_obj.nombre}.",
                    )
                else:
                    messages.warning(
                        request,
                        "No se encontró un registro previo para eliminar.",
                    )
            else:
                messages.error(request, "Acción no reconocida.")
            return redirect(redirect_url)

        errors = ", ".join(
            [str(error) for error_list in form.errors.values() for error in error_list]
        )
        if errors:
            messages.error(request, errors)
        return redirect(redirect_actual)

    especie_normalizada = (
        _normalizar_especie_mascota(mascota_seleccionada.especie)
        if mascota_seleccionada
        else ""
    )

    vacunas_recomendadas = []
    registros_por_vacuna = {}

    if vacunas_disponibles and mascota_seleccionada and especie_normalizada:
        vacunas_recomendadas = list(
            VacunaRecomendada.objects.filter(especie=especie_normalizada).order_by(
                "orden", "nombre"
            )
        )
        registros_por_vacuna = {
            registro.vacuna_id: registro
            for registro in VacunaRegistro.objects.filter(
                paciente=mascota_seleccionada,
                vacuna__in=vacunas_recomendadas,
            )
        }

    vacunas_info = [
        {
            "vacuna": vacuna,
            "registro": registros_por_vacuna.get(vacuna.id),
        }
        for vacuna in vacunas_recomendadas
    ]

    total_vacunas = len(vacunas_recomendadas)
    completadas = sum(1 for item in vacunas_info if item["registro"])
    porcentaje_avance = int((completadas / total_vacunas) * 100) if total_vacunas else 0

    return render(
        request,
        "core/calendario_vacunas.html",
        {
            "mascotas": mascotas,
            "mascota_seleccionada": mascota_seleccionada,
            "vacunas_info": vacunas_info,
            "especie_normalizada": especie_normalizada,
            "vacunas_disponibles": vacunas_disponibles,
            "total_vacunas": total_vacunas,
            "vacunas_completadas": completadas,
            "vacunas_pendientes": max(total_vacunas - completadas, 0),
            "porcentaje_avance": porcentaje_avance,
            "hoy": timezone.localdate(),
        },
    )


@login_required
def mis_mascotas(request):
    propietario = get_object_or_404(Propietario, user=request.user)
    mascotas = Paciente.objects.filter(propietario=propietario)
    return render(request, "core/mis_mascotas.html", {"mascotas": mascotas})


@login_required
def detalle_mascota(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)

    if request.user.rol == "OWNER" and paciente.propietario.user != request.user:
        messages.error(request, "No tienes permiso para ver esta mascota.")
        return redirect("dashboard")

    historiales_qs = HistorialMedico.objects.filter(paciente=paciente).order_by("-fecha")
    historiales = list(historiales_qs)

    citas_qs = (
        Cita.objects.filter(paciente=paciente)
        .select_related("veterinario", "historial_medico")
        .order_by("-fecha_solicitada", "-fecha_hora")
    )
    citas = list(citas_qs)

    historiales_por_fecha = {}
    for historial in historiales:
        fecha_hist = historial.fecha
        if timezone.is_aware(fecha_hist):
            fecha_hist = timezone.localtime(fecha_hist)
        historiales_por_fecha.setdefault(fecha_hist.date(), historial)

    for cita in citas:
        historial_relacionado = getattr(cita, "historial_medico", None)
        if historial_relacionado:
            cita.historial_relacionado = historial_relacionado
            continue

        fecha_cita = cita.fecha_hora
        if fecha_cita:
            if timezone.is_aware(fecha_cita):
                fecha_cita = timezone.localtime(fecha_cita)
        else:
            fecha_cita = datetime.combine(cita.fecha_solicitada, time.min)
            if timezone.is_naive(fecha_cita):
                fecha_cita = timezone.make_aware(
                    fecha_cita, timezone.get_current_timezone()
                )

        cita.historial_relacionado = historiales_por_fecha.get(fecha_cita.date())

    ahora = timezone.now()
    citas_confirmadas = [cita for cita in citas if cita.fecha_hora]
    citas_futuras = sorted(
        (cita for cita in citas_confirmadas if cita.fecha_hora >= ahora),
        key=lambda c: c.fecha_hora,
    )
    citas_pasadas = [
        cita for cita in citas_confirmadas if cita.fecha_hora < ahora
    ]

    ultima_consulta = historiales[0] if historiales else None
    proxima_cita = citas_futuras[0] if citas_futuras else None

    template = (
        "core/detalle_mascota_admin.html"
        if request.user.rol in {"ADMIN", "ADMIN_OP"}
        else "core/detalle_mascota.html"
    )
    return render(
        request,
        template,
        {
            "paciente": paciente,
            "historiales": historiales,
            "citas": citas,
            "citas_futuras": citas_futuras,
            "citas_pasadas": citas_pasadas,
            "ultima_consulta": ultima_consulta,
            "proxima_cita": proxima_cita,
        },
    )


@login_required
def registrar_historial(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)

    if request.user.rol != "VET":
        messages.error(request, "No tienes permiso para registrar historial médico.")
        return redirect("dashboard")

    cita_asociada = None
    cita_id_param = request.GET.get("cita") or request.POST.get("cita_id")
    if cita_id_param:
        try:
            cita_asociada = Cita.objects.select_related("paciente").get(
                id=cita_id_param, paciente=paciente
            )
        except Cita.DoesNotExist:
            cita_asociada = None
            messages.warning(
                request,
                "La cita seleccionada no pertenece a este paciente o ya no está disponible.",
            )

    if request.method == "POST":
        diagnostico = request.POST.get("diagnostico")
        tratamiento = request.POST.get("tratamiento")
        notas = request.POST.get("notas")
        peso = request.POST.get("peso") or None
        temperatura = request.POST.get("temperatura") or None
        examenes = request.POST.get("examenes")
        proximo_control = request.POST.get("proximo_control") or None
        sin_proximo_control = bool(request.POST.get("sin_proximo_control"))
        adjuntar_estudios = bool(request.POST.get("adjuntar_estudios"))

        if sin_proximo_control:
            proximo_control = None

        historial_defaults = {
            "paciente": paciente,
            "veterinario": request.user,
            "diagnostico": diagnostico,
            "tratamiento": tratamiento,
            "notas": notas,
            "peso": peso,
            "temperatura": temperatura,
            "examenes": examenes,
            "proximo_control": proximo_control,
            "sin_proximo_control": sin_proximo_control,
        }

        if adjuntar_estudios and "estudio_imagen" in request.FILES:
            historial_defaults["imagenes"] = request.FILES["estudio_imagen"]

        if cita_asociada:
            HistorialMedico.objects.update_or_create(
                cita=cita_asociada, defaults=historial_defaults
            )
            if cita_asociada.estado != "atendida":
                cita_asociada.estado = "atendida"
                cita_asociada.save(update_fields=["estado"])
        else:
            HistorialMedico.objects.create(**historial_defaults)

        messages.success(request, "Historial médico registrado correctamente ✅")
        return redirect("detalle_mascota", paciente_id=paciente.id)

    return render(
        request,
        "core/registrar_historial.html",
        {"paciente": paciente, "cita_asociada": cita_asociada},
    )


@login_required
def listar_usuarios(request):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para ver esta página.")
        return redirect("dashboard")

    usuarios = User.objects.all().order_by("username")
    return render(request, "core/usuarios.html", {"usuarios": usuarios})


@login_required
def listar_pacientes(request):
    if request.user.rol not in {"ADMIN", "ADMIN_OP"}:
        messages.error(request, "No tienes permiso para ver esta página.")
        return redirect("dashboard")

    pacientes = Paciente.objects.all().order_by("nombre")
    return render(request, "core/pacientes.html", {"pacientes": pacientes})


@login_required
def registrar_mascota(request):
    if request.user.rol != "OWNER":
        messages.error(request, "No tienes permiso para registrar mascotas.")
        return redirect("dashboard")

    propietario = get_object_or_404(Propietario, user=request.user)
    form_data = request.POST if request.method == "POST" else {}
    foto_subida = None

    if request.method == "POST":
        has_error = False
        nombre = request.POST.get("nombre")
        especie = request.POST.get("especie")
        raza = request.POST.get("raza")
        sexo = request.POST.get("sexo")
        fecha_nacimiento = request.POST.get("fecha_nacimiento")
        foto_subida = request.FILES.get("foto")

        fecha_obj = None
        if fecha_nacimiento:
            try:
                fecha_obj = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "La fecha de nacimiento no es válida.")
                has_error = True
        else:
            messages.error(request, "Debes indicar la fecha de nacimiento.")
            has_error = True

        if not has_error:
            Paciente.objects.create(
                nombre=nombre,
                especie=especie,
                raza=raza,
                sexo=sexo,
                fecha_nacimiento=fecha_obj,
                propietario=propietario,
                foto=foto_subida,
            )
            messages.success(
                request, f"Mascota {nombre} registrada correctamente ✅"
            )
            return redirect("mis_mascotas")

    return render(
        request,
        "core/registrar_mascota.html",
        {"form_data": form_data, "foto_subida": foto_subida},
    )


# ----------------------------
# Citas
# ----------------------------


@login_required
def mis_citas(request):
    user = request.user
    filtros_estado = request.GET.get("estado", "").strip()
    filtro_busqueda = request.GET.get("q", "").strip()
    filtro_desde = request.GET.get("desde", "").strip()
    filtro_hasta = request.GET.get("hasta", "").strip()

    base_queryset = (
        Cita.objects.select_related(
            "paciente",
            "paciente__propietario__user",
            "veterinario",
            "historial_medico",
        ).prefetch_related(
            "farmacos_utilizados",
            "administraciones_farmacos__farmaco",
        )
    )

    queryset = base_queryset

    propietario = None
    if user.rol == "VET":
        queryset = queryset.filter(veterinario=user)
    elif user.rol == "OWNER":
        propietario = (
            Propietario.objects.select_related("user").filter(user=user).first()
        )
        if propietario:
            queryset = queryset.filter(paciente__propietario=propietario)
        else:
            queryset = queryset.none()
            messages.warning(
                request,
                "Completa tu perfil de propietario para comenzar a registrar y seguir tus citas.",
            )
    elif user.rol in {"ADMIN_OP", "ADMIN"}:
        queryset = _filtrar_por_sucursal(queryset, user)
    else:
        queryset = queryset.none()

    if filtros_estado:
        queryset = queryset.filter(estado=filtros_estado)

    if filtro_busqueda:
        queryset = queryset.filter(
            Q(paciente__nombre__icontains=filtro_busqueda)
            | Q(paciente__propietario__user__first_name__icontains=filtro_busqueda)
            | Q(paciente__propietario__user__last_name__icontains=filtro_busqueda)
            | Q(veterinario__first_name__icontains=filtro_busqueda)
            | Q(veterinario__last_name__icontains=filtro_busqueda)
            | Q(notas__icontains=filtro_busqueda)
        )

    fecha_desde = None
    if filtro_desde:
        try:
            fecha_desde = datetime.strptime(filtro_desde, "%Y-%m-%d").date()
        except ValueError:
            messages.warning(request, "La fecha desde ingresada no es válida.")
        else:
            queryset = queryset.filter(fecha_solicitada__gte=fecha_desde)

    fecha_hasta = None
    if filtro_hasta:
        try:
            fecha_hasta = datetime.strptime(filtro_hasta, "%Y-%m-%d").date()
        except ValueError:
            messages.warning(request, "La fecha hasta ingresada no es válida.")
        else:
            queryset = queryset.filter(fecha_solicitada__lte=fecha_hasta)

    queryset = queryset.order_by("-fecha_solicitada", "-fecha_hora")

    citas = list(queryset)

    ahora = timezone.now()
    citas_proximas = []
    citas_pasadas = []
    citas_pendientes = []
    estado_resumen = {estado: 0 for estado, _ in Cita.ESTADOS}
    sin_veterinario = 0

    for cita in citas:
        estado_resumen[cita.estado] = estado_resumen.get(cita.estado, 0) + 1
        if not cita.veterinario_id:
            sin_veterinario += 1

        if cita.fecha_hora:
            if cita.fecha_hora >= ahora:
                citas_proximas.append(cita)
            else:
                citas_pasadas.append(cita)
        else:
            citas_pendientes.append(cita)

    context = {
        "citas": citas,
        "citas_proximas": sorted(citas_proximas, key=lambda c: c.fecha_hora),
        "citas_pendientes": sorted(
            citas_pendientes,
            key=lambda c: (
                c.fecha_solicitada or timezone.localdate(),
                c.paciente.nombre,
            ),
        ),
        "citas_pasadas": sorted(
            citas_pasadas,
            key=lambda c: c.fecha_hora,
            reverse=True,
        ),
        "estadisticas_citas": {
            "total": len(citas),
            "programadas": estado_resumen.get("programada", 0),
            "pendientes": estado_resumen.get("pendiente", 0),
            "atendidas": estado_resumen.get("atendida", 0),
            "canceladas": estado_resumen.get("cancelada", 0),
            "sin_veterinario": sin_veterinario,
        },
        "filtros": {
            "estado": filtros_estado,
            "q": filtro_busqueda,
            "desde": filtro_desde,
            "hasta": filtro_hasta,
        },
        "propietario": propietario,
        "estados": Cita.ESTADOS,
    }

    return render(request, "core/mis_citas.html", context)


@login_required
def agendar_cita(request, paciente_id=None):
    if request.user.rol != "OWNER":
        messages.error(request, "No tienes permiso para agendar citas.")
        return redirect("dashboard")

    propietario = get_object_or_404(Propietario, user=request.user)
    mascotas = Paciente.objects.filter(propietario=propietario)
    paciente_seleccionado = None
    sucursales = Sucursal.objects.all().order_by("nombre")
    sucursal_seleccionada = None

    if request.method == "POST":
        paciente_id_form = request.POST.get("paciente")
        fecha_solicitada_raw = request.POST.get("fecha_solicitada")
        notas = request.POST.get("notas", "").strip()
        sucursal_id = request.POST.get("sucursal")

        paciente = get_object_or_404(
            Paciente, id=paciente_id_form, propietario=propietario
        )
        paciente_seleccionado = paciente

        try:
            sucursal = Sucursal.objects.get(id=sucursal_id)
        except Sucursal.DoesNotExist:
            messages.error(request, "Selecciona una sucursal válida para la cita.")
            sucursal = None
        else:
            sucursal_seleccionada = sucursal

        if not fecha_solicitada_raw:
            messages.error(
                request, "Debes seleccionar un día válido para la cita."
            )
        elif sucursal:
            try:
                fecha_solicitada = datetime.strptime(
                    fecha_solicitada_raw, "%Y-%m-%d"
                ).date()
            except ValueError:
                messages.error(request, "El formato de la fecha no es válido.")
            else:
                hoy = timezone.localdate()
                if fecha_solicitada < hoy:
                    messages.error(
                        request,
                        "El día seleccionado ya pasó. Elige una fecha futura.",
                    )
                else:
                    Cita.objects.create(
                        paciente=paciente,
                        fecha_solicitada=fecha_solicitada,
                        notas=notas,
                        sucursal=sucursal,
                        estado="pendiente",
                    )
                    messages.success(
                        request,
                        (
                            "Solicitud registrada para {nombre}. Nuestro equipo te contactará "
                            "por WhatsApp para coordinar el horario."
                        ).format(nombre=paciente.nombre),
                    )
                    return redirect("mis_citas")

    if paciente_id and paciente_seleccionado is None:
        paciente_seleccionado = get_object_or_404(
            Paciente, id=paciente_id, propietario=propietario
        )

    return render(
        request,
        "core/agendar_cita.html",
        {
            "mascotas": mascotas,
            "paciente_seleccionado": paciente_seleccionado,
            "sucursales": sucursales,
            "sucursal_seleccionada": sucursal_seleccionada,
        },
    )


@login_required
def asignar_veterinario_cita(request, cita_id):
    if request.user.rol not in {"ADMIN", "ADMIN_OP"}:
        messages.error(request, "No tienes permiso para asignar veterinarios a las citas.")
        return redirect("dashboard")

    cita = get_object_or_404(
        _filtrar_por_sucursal(Cita.objects.all(), request.user),
        id=cita_id,
    )
    veterinarios = _veterinarios_activos(cita.sucursal)

    if request.method == "POST":
        vet_id = request.POST.get("veterinario")
        fecha_raw = request.POST.get("fecha")
        hora_raw = request.POST.get("hora")

        if not vet_id:
            messages.error(
                request, "Debes seleccionar un veterinario para asignar la cita."
            )
        elif not fecha_raw or not hora_raw:
            messages.error(
                request, "Completa la fecha y el horario confirmados para la cita."
            )
        else:
            try:
                fecha_confirmada = datetime.strptime(fecha_raw, "%Y-%m-%d").date()
                hora_confirmada = datetime.strptime(hora_raw, "%H:%M").time()
            except ValueError:
                messages.error(request, "El formato de fecha u hora no es válido.")
            else:
                fecha_hora = datetime.combine(fecha_confirmada, hora_confirmada)
                if timezone.is_naive(fecha_hora):
                    fecha_hora = timezone.make_aware(
                        fecha_hora, timezone.get_current_timezone()
                    )

                if fecha_hora < timezone.now():
                    messages.error(
                        request,
                        "El horario confirmado no puede estar en el pasado.",
                    )
                else:
                    veterinario = get_object_or_404(
                        User,
                        id=vet_id,
                        rol="VET",
                        sucursal=cita.sucursal,
                        activo=True,
                        is_active=True,
                    )
                    cita.veterinario = veterinario
                    cita.fecha_hora = fecha_hora
                    cita.fecha_solicitada = fecha_confirmada
                    cita.estado = "programada"
                    cita.save(
                        update_fields=[
                            "veterinario",
                            "fecha_hora",
                            "fecha_solicitada",
                            "estado",
                        ]
                    )
                    nombre_vet = veterinario.get_full_name() or veterinario.username
                    messages.success(
                        request,
                        (
                            "Cita programada con {vet}. Horario confirmado para el {fecha}."
                        ).format(
                            vet=nombre_vet,
                            fecha=fecha_hora.strftime("%d/%m/%Y %H:%M"),
                        ),
                    )
                    return redirect("listar_citas_admin")

    return render(
        request,
        "core/asignar_veterinario.html",
        {"cita": cita, "veterinarios": veterinarios},
    )


@login_required
def listar_citas_admin(request):
    if request.user.rol not in {"ADMIN", "ADMIN_OP"}:
        messages.error(request, "No tienes permiso para ver esta página.")
        return redirect("dashboard")

    if not request.user.is_superuser and not getattr(request.user, "sucursal_id", None):
        messages.warning(
            request,
            "Asigna una sucursal a tu perfil para administrar las citas.",
        )

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        cita_id = request.POST.get("cita_id")
        redirect_url = request.POST.get("redirect") or reverse("listar_citas_admin")

        if not cita_id:
            messages.error(request, "Selecciona una cita para aplicar la acción.")
            return redirect(redirect_url)

        cita = get_object_or_404(
            _filtrar_por_sucursal(Cita.objects.all(), request.user),
            id=cita_id,
        )

        if action == "cancelar":
            if cita.estado == "cancelada":
                messages.info(request, "La cita ya se encuentra cancelada.")
            else:
                cita.estado = "cancelada"
                cita.save(update_fields=["estado"])
                messages.success(
                    request,
                    f"Cita de {cita.paciente.nombre} cancelada correctamente.",
                )
        elif action == "marcar_atendida":
            if cita.estado == "atendida":
                messages.info(request, "La cita ya estaba marcada como atendida.")
            else:
                cita.estado = "atendida"
                if not cita.fecha_hora:
                    cita.fecha_hora = timezone.now()
                    cita.save(update_fields=["estado", "fecha_hora"])
                else:
                    cita.save(update_fields=["estado"])
                messages.success(
                    request,
                    f"Cita de {cita.paciente.nombre} marcada como atendida.",
                )
        elif action == "reactivar":
            cita.estado = "pendiente"
            cita.fecha_hora = None
            cita.veterinario = None
            cita.save(update_fields=["estado", "fecha_hora", "veterinario"])
            messages.success(
                request,
                f"Cita de {cita.paciente.nombre} reabierta para reasignar horario.",
            )
        else:
            messages.error(request, "Acción no reconocida.")

        return redirect(redirect_url)

    filtro_estado = request.GET.get("estado", "").strip()
    filtro_veterinario = request.GET.get("veterinario", "").strip()
    filtro_propietario = request.GET.get("propietario", "").strip()
    filtro_tipo = request.GET.get("tipo", "").strip()
    filtro_busqueda = request.GET.get("q", "").strip()
    filtro_desde = request.GET.get("desde", "").strip()
    filtro_hasta = request.GET.get("hasta", "").strip()
    filtro_sin_veterinario = request.GET.get("sin_veterinario") == "1"

    queryset = Cita.objects.select_related(
        "paciente",
        "paciente__propietario__user",
        "veterinario",
        "historial_medico",
    )
    queryset = _filtrar_por_sucursal(queryset, request.user)

    if filtro_estado:
        queryset = queryset.filter(estado=filtro_estado)

    if filtro_tipo:
        queryset = queryset.filter(tipo=filtro_tipo)

    if filtro_veterinario == "sin_asignar":
        queryset = queryset.filter(veterinario__isnull=True)
    elif filtro_veterinario:
        queryset = queryset.filter(veterinario_id=filtro_veterinario)

    if filtro_propietario:
        queryset = queryset.filter(paciente__propietario_id=filtro_propietario)

    if filtro_sin_veterinario:
        queryset = queryset.filter(veterinario__isnull=True)

    if filtro_busqueda:
        queryset = queryset.filter(
            Q(paciente__nombre__icontains=filtro_busqueda)
            | Q(paciente__propietario__user__first_name__icontains=filtro_busqueda)
            | Q(paciente__propietario__user__last_name__icontains=filtro_busqueda)
            | Q(veterinario__first_name__icontains=filtro_busqueda)
            | Q(veterinario__last_name__icontains=filtro_busqueda)
            | Q(notas__icontains=filtro_busqueda)
        )

    if filtro_desde:
        try:
            fecha_desde = datetime.strptime(filtro_desde, "%Y-%m-%d").date()
        except ValueError:
            messages.warning(request, "La fecha desde ingresada no es válida.")
        else:
            queryset = queryset.filter(fecha_solicitada__gte=fecha_desde)

    if filtro_hasta:
        try:
            fecha_hasta = datetime.strptime(filtro_hasta, "%Y-%m-%d").date()
        except ValueError:
            messages.warning(request, "La fecha hasta ingresada no es válida.")
        else:
            queryset = queryset.filter(fecha_solicitada__lte=fecha_hasta)

    queryset = queryset.order_by("-fecha_solicitada", "-fecha_hora")

    citas = list(queryset)

    resumen_filtrado = {estado: 0 for estado, _ in Cita.ESTADOS}
    for cita in citas:
        resumen_filtrado[cita.estado] = resumen_filtrado.get(cita.estado, 0) + 1

    resumen_global = {estado: 0 for estado, _ in Cita.ESTADOS}
    for item in queryset.values("estado").annotate(total=Count("id")):
        resumen_global[item["estado"]] = item["total"]

    proximas_citas = [
        cita
        for cita in citas
        if cita.fecha_hora and cita.estado in {"programada", "pendiente"}
    ]
    proximas_citas.sort(key=lambda c: c.fecha_hora or timezone.now())

    veterinarios = _filtrar_por_sucursal(
        _veterinarios_activos(),
        request.user,
    )
    propietarios = _filtrar_por_sucursal(
        Propietario.objects.select_related("user"),
        request.user,
        field_name="paciente__cita__sucursal",
    ).distinct().order_by("user__first_name", "user__last_name")

    querystring = request.GET.urlencode()
    redirect_target = reverse("listar_citas_admin")
    if querystring:
        redirect_target = f"{redirect_target}?{querystring}"

    total_global = sum(resumen_global.values())

    sucursal_activa = None
    if not request.user.is_superuser and request.user.rol in _roles_con_sucursal():
        sucursal_activa = request.user.sucursal

    context = {
        "citas": citas,
        "total_citas": len(citas),
        "resumen_filtrado": resumen_filtrado,
        "resumen_global": resumen_global,
        "proximas_citas": proximas_citas[:5],
        "filtros": {
            "estado": filtro_estado,
            "veterinario": filtro_veterinario,
            "propietario": filtro_propietario,
            "tipo": filtro_tipo,
            "q": filtro_busqueda,
            "desde": filtro_desde,
            "hasta": filtro_hasta,
            "sin_veterinario": filtro_sin_veterinario,
        },
        "estados": Cita.ESTADOS,
        "tipos": Cita.TIPOS,
        "veterinarios": veterinarios,
        "propietarios": propietarios,
        "querystring": querystring,
        "redirect_target": redirect_target,
        "total_global": total_global,
        "sucursal_activa": sucursal_activa,
        "es_superadmin": request.user.is_superuser,
    }

    return render(request, "core/citas_admin.html", context)


@login_required
def asignar_veterinario_citas(request):
    if request.user.rol not in {"ADMIN", "ADMIN_OP"}:
        messages.error(request, "No tienes permiso para gestionar estas citas.")
        return redirect("dashboard")

    if not request.user.is_superuser and not getattr(request.user, "sucursal_id", None):
        messages.warning(
            request,
            "Asigna una sucursal a tu perfil para coordinar turnos pendientes.",
        )

    veterinarios_queryset = _filtrar_por_sucursal(
        _veterinarios_activos().select_related("sucursal"),
        request.user,
    )
    veterinarios_por_sucursal = defaultdict(list)
    for veterinario in veterinarios_queryset:
        veterinarios_por_sucursal[veterinario.sucursal_id].append(veterinario)

    citas_pendientes = list(
        _filtrar_por_sucursal(
            Cita.objects.select_related(
                "paciente",
                "paciente__propietario__user",
                "sucursal",
            )
            .filter(estado="pendiente")
            .order_by("fecha_solicitada", "fecha_hora"),
            request.user,
        )
    )
    for cita in citas_pendientes:
        cita.veterinarios_disponibles = veterinarios_por_sucursal.get(
            cita.sucursal_id, []
        )

    if request.method == "POST":
        cita_id = request.POST.get("cita")
        vet_id = request.POST.get("veterinario")
        fecha_raw = request.POST.get("fecha")
        hora_raw = request.POST.get("hora")

        if not cita_id or not vet_id:
            messages.error(request, "Selecciona una cita y un veterinario válidos.")
        elif not fecha_raw or not hora_raw:
            messages.error(request, "Debes ingresar la fecha y hora confirmadas.")
        else:
            cita = get_object_or_404(
                _filtrar_por_sucursal(
                    Cita.objects.filter(estado__in=["pendiente", "programada"]),
                    request.user,
                ),
                id=cita_id,
            )
            try:
                fecha_confirmada = datetime.strptime(fecha_raw, "%Y-%m-%d").date()
                hora_confirmada = datetime.strptime(hora_raw, "%H:%M").time()
            except ValueError:
                messages.error(request, "Formato de fecha u hora inválido.")
            else:
                fecha_hora = datetime.combine(fecha_confirmada, hora_confirmada)
                if timezone.is_naive(fecha_hora):
                    fecha_hora = timezone.make_aware(
                        fecha_hora, timezone.get_current_timezone()
                    )

                if fecha_hora < timezone.now():
                    messages.error(
                        request,
                        "El horario confirmado no puede estar en el pasado.",
                    )
                else:
                    veterinario = get_object_or_404(
                        User,
                        id=vet_id,
                        rol="VET",
                        sucursal=cita.sucursal,
                        activo=True,
                        is_active=True,
                    )
                    cita.veterinario = veterinario
                    cita.fecha_hora = fecha_hora
                    cita.fecha_solicitada = fecha_confirmada
                    cita.estado = "programada"
                    cita.save(
                        update_fields=[
                            "veterinario",
                            "fecha_hora",
                            "fecha_solicitada",
                            "estado",
                        ]
                    )
                    nombre_vet = veterinario.get_full_name() or veterinario.username
                    messages.success(
                        request,
                        (
                            "Veterinario {vet} asignado a {paciente}. Cita confirmada para {fecha}."
                        ).format(
                            vet=nombre_vet,
                            paciente=cita.paciente.nombre,
                            fecha=fecha_hora.strftime("%d/%m/%Y %H:%M"),
                        ),
                    )
                    return redirect("asignar_veterinario_citas")

    return render(
        request,
        "core/asignar_veterinario_citas.html",
        {
            "citas_pendientes": citas_pendientes,
        },
    )


@login_required
def atender_cita(request, cita_id):
    cita = get_object_or_404(
        Cita.objects.select_related("paciente", "paciente__propietario__user")
        .prefetch_related("farmacos_utilizados", "administraciones_farmacos__farmaco"),
        id=cita_id,
    )

    if request.user.rol != "VET":
        messages.error(request, "No tienes permiso para atender esta cita.")
        return redirect("dashboard")

    if not _usuario_puede_gestionar_sucursal(request.user, cita.sucursal_id):
        messages.error(
            request,
            "No tienes permiso para operar sobre citas de otra sucursal.",
        )
        return redirect("dashboard")

    if cita.veterinario_id and cita.veterinario_id != request.user.id:
        messages.error(
            request,
            "Esta cita está asignada a otro profesional.",
        )
        return redirect("dashboard")

    historial_existente = getattr(cita, "historial_medico", None)
    administraciones_actuales = list(
        cita.administraciones_farmacos.select_related("farmaco").order_by(
            "farmaco__nombre"
        )
    )
    administraciones_por_id = {
        admin.farmaco_id: admin for admin in administraciones_actuales
    }

    farmacos_qs = list(
        Farmaco.objects.filter(sucursal=cita.sucursal)
        .order_by("categoria", "nombre")
        .select_related("sucursal")
    )
    inventario_por_id = {farmaco.id: farmaco for farmaco in farmacos_qs}

    farmacos_catalogo = []
    catalogo_por_codigo = {}
    for farmaco in farmacos_qs:
        catalogo_por_codigo.setdefault(farmaco.categoria, []).append(farmaco)
    for codigo, etiqueta in Farmaco.Categoria.choices:
        items = catalogo_por_codigo.get(codigo, [])
        if items:
            farmacos_catalogo.append(
                {
                    "codigo": codigo,
                    "nombre": etiqueta,
                    "items": items,
                }
            )

    farmacos_serializados = [
        {
            "id": farmaco.id,
            "nombre": farmaco.nombre,
            "categoria": farmaco.categoria,
            "categoria_nombre": farmaco.get_categoria_display(),
            "descripcion": farmaco.descripcion or "",
            "stock": farmaco.stock,
        }
        for farmaco in farmacos_qs
    ]

    seleccion_detalle = [
        {
            "id": admin.farmaco_id,
            "nombre": admin.farmaco.nombre,
            "categoria": admin.farmaco.categoria,
            "categoria_nombre": admin.farmaco.get_categoria_display(),
            "descripcion": admin.farmaco.descripcion,
            "stock": admin.farmaco.stock,
            "cantidad": admin.cantidad,
        }
        for admin in administraciones_actuales
    ]

    utilizo_farmacos = bool(seleccion_detalle)
    form_values = {}

    if request.method == "POST":
        diagnostico = request.POST.get("diagnostico")
        tratamiento = request.POST.get("tratamiento")
        notas = request.POST.get("notas")
        peso = request.POST.get("peso") or None
        temperatura = request.POST.get("temperatura") or None
        examenes = request.POST.get("examenes")
        proximo_control = request.POST.get("proximo_control") or None
        sin_proximo_control = bool(request.POST.get("sin_proximo_control"))
        adjuntar_estudios = bool(request.POST.get("adjuntar_estudios"))
        utilizo_farmacos = bool(request.POST.get("utilizo_farmacos"))
        entradas_farmacos = request.POST.getlist("farmacos_utilizados")

        if sin_proximo_control:
            proximo_control = None

        form_values = {
            "diagnostico": diagnostico,
            "tratamiento": tratamiento,
            "notas": notas,
            "peso": peso or "",
            "temperatura": temperatura or "",
            "examenes": examenes,
            "proximo_control": proximo_control or "",
            "sin_proximo_control": sin_proximo_control,
            "adjuntar_estudios": adjuntar_estudios,
        }

        seleccion_post = []
        mensajes_error = []
        for entrada in entradas_farmacos:
            try:
                farmaco_id_raw, cantidad_raw = entrada.split("::", 1)
                farmaco_id = int(farmaco_id_raw)
                cantidad = int(cantidad_raw)
            except (TypeError, ValueError):
                mensajes_error.append(
                    "No se pudo interpretar la selección de fármacos enviada. Intentalo nuevamente."
                )
                continue

            if cantidad <= 0:
                mensajes_error.append(
                    "Ingresá una cantidad válida (mayor que cero) para cada fármaco utilizado."
                )
                continue

            seleccion_post.append((farmaco_id, cantidad))

        if utilizo_farmacos and not seleccion_post:
            mensajes_error.append(
                "Seleccioná al menos un fármaco del inventario e indicá la cantidad administrada."
            )

        if mensajes_error:
            for mensaje in mensajes_error:
                messages.error(request, mensaje)

        if not mensajes_error:
            try:
                with transaction.atomic():
                    historial_defaults = {
                        "paciente": cita.paciente,
                        "veterinario": request.user,
                        "diagnostico": diagnostico,
                        "tratamiento": tratamiento,
                        "notas": notas,
                        "peso": peso,
                        "temperatura": temperatura,
                        "examenes": examenes,
                        "proximo_control": proximo_control,
                        "sin_proximo_control": sin_proximo_control,
                    }

                    if adjuntar_estudios and "estudio_imagen" in request.FILES:
                        historial_defaults["imagenes"] = request.FILES["estudio_imagen"]

                    HistorialMedico.objects.update_or_create(
                        cita=cita,
                        defaults=historial_defaults,
                    )

                    cita.estado = "atendida"
                    cita.save(update_fields=["estado"])

                    if utilizo_farmacos:
                        existentes = {
                            admin.farmaco_id: admin
                            for admin in CitaFarmaco.objects.select_for_update().filter(
                                cita=cita
                            )
                        }
                        nuevos_map = {fid: cantidad for fid, cantidad in seleccion_post}
                        ids_para_bloquear = set(existentes.keys()) | set(nuevos_map.keys())

                        if ids_para_bloquear:
                            farmacos_map = {
                                farmaco.id: farmaco
                                for farmaco in Farmaco.objects.select_for_update()
                                .filter(sucursal=cita.sucursal, id__in=ids_para_bloquear)
                            }

                            faltantes = ids_para_bloquear - set(farmacos_map.keys())
                            if faltantes:
                                raise ValueError(
                                    "Uno de los fármacos seleccionados ya no pertenece al inventario de la sucursal."
                                )

                            for fid in ids_para_bloquear:
                                anterior = existentes.get(fid)
                                anterior_cantidad = anterior.cantidad if anterior else 0
                                nueva_cantidad = nuevos_map.get(fid, 0)
                                delta = nueva_cantidad - anterior_cantidad
                                if delta > 0 and farmacos_map[fid].stock < delta:
                                    raise ValueError(
                                        (
                                            "Stock insuficiente para {nombre}. Disponible: {disponible}."
                                        ).format(
                                            nombre=farmacos_map[fid].nombre,
                                            disponible=farmacos_map[fid].stock,
                                        )
                                    )

                            for fid in ids_para_bloquear:
                                anterior = existentes.get(fid)
                                anterior_cantidad = anterior.cantidad if anterior else 0
                                nueva_cantidad = nuevos_map.get(fid, 0)
                                delta = nueva_cantidad - anterior_cantidad
                                if delta:
                                    Farmaco.objects.filter(
                                        id=fid, sucursal=cita.sucursal
                                    ).update(stock=F("stock") - delta)

                            for fid, cantidad in nuevos_map.items():
                                registro = existentes.get(fid)
                                if registro:
                                    if registro.cantidad != cantidad:
                                        registro.cantidad = cantidad
                                        registro.save(update_fields=["cantidad"])
                                else:
                                    CitaFarmaco.objects.create(
                                        cita=cita,
                                        farmaco_id=fid,
                                        cantidad=cantidad,
                                    )

                            for fid, registro in existentes.items():
                                if fid not in nuevos_map:
                                    registro.delete()
                    else:
                        registros_previos = list(
                            CitaFarmaco.objects.select_for_update().filter(cita=cita)
                        )
                        if registros_previos:
                            for registro in registros_previos:
                                Farmaco.objects.filter(
                                    id=registro.farmaco_id, sucursal=cita.sucursal
                                ).update(stock=F("stock") + registro.cantidad)
                                registro.delete()

            except ValueError as error:
                messages.error(request, str(error))
            else:
                messages.success(
                    request,
                    f"Cita de {cita.paciente.nombre} atendida correctamente ✅",
                )
                return redirect("detalle_cita", cita_id=cita.id)

        if seleccion_post:
            seleccion_detalle = []
            for fid, cantidad in seleccion_post:
                farmaco = inventario_por_id.get(fid)
                if not farmaco:
                    registro_previo = administraciones_por_id.get(fid)
                    farmaco = registro_previo.farmaco if registro_previo else None
                if not farmaco:
                    continue
                seleccion_detalle.append(
                    {
                        "id": fid,
                        "cantidad": cantidad,
                        "nombre": farmaco.nombre,
                        "categoria": farmaco.categoria,
                        "categoria_nombre": farmaco.get_categoria_display(),
                        "descripcion": farmaco.descripcion,
                        "stock": farmaco.stock,
                    }
                )

    if "sin_proximo_control" not in form_values:
        form_values["sin_proximo_control"] = bool(
            getattr(historial_existente, "sin_proximo_control", False)
        )
    if "proximo_control" not in form_values and getattr(
        historial_existente, "proximo_control", None
    ):
        form_values["proximo_control"] = (
            historial_existente.proximo_control.strftime("%Y-%m-%d")
        )
    if "peso" not in form_values and getattr(historial_existente, "peso", None) is not None:
        form_values["peso"] = str(historial_existente.peso)
    if "temperatura" not in form_values and getattr(
        historial_existente, "temperatura", None
    ) is not None:
        form_values["temperatura"] = str(historial_existente.temperatura)
    if "adjuntar_estudios" not in form_values:
        form_values["adjuntar_estudios"] = False
    for campo in ("diagnostico", "tratamiento", "notas", "examenes"):
        if campo not in form_values and historial_existente:
            form_values[campo] = getattr(historial_existente, campo, "") or ""

    contexto = {
        "cita": cita,
        "historial_existente": historial_existente,
        "farmacos_catalogo": farmacos_catalogo,
        "farmacos_disponibles_json": farmacos_serializados,
        "farmacos_seleccionados": seleccion_detalle,
        "utilizo_farmacos": utilizo_farmacos,
        "form_values": form_values,
    }

    return render(request, "core/atender_cita.html", contexto)


@login_required
def mis_historiales(request):
    if request.user.rol != "VET":
        messages.error(request, "No tienes permiso para ver esta página.")
        return redirect("dashboard")

    historiales = HistorialMedico.objects.filter(veterinario=request.user).order_by(
        "-fecha"
    )
    return render(request, "core/mis_historiales.html", {"historiales": historiales})


@login_required
def detalle_cita(request, cita_id):
    base_queryset = (
        Cita.objects.select_related(
            "paciente",
            "paciente__propietario__user",
            "veterinario",
            "historial_medico",
        ).prefetch_related(
            "farmacos_utilizados",
            "administraciones_farmacos__farmaco",
        )
    )
    if request.user.rol in {"ADMIN", "ADMIN_OP"}:
        base_queryset = _filtrar_por_sucursal(base_queryset, request.user)

    cita = get_object_or_404(base_queryset, id=cita_id)

    if request.user.rol == "OWNER" and cita.paciente.propietario.user != request.user:
        messages.error(request, "No tienes permiso para ver esta cita.")
        return redirect("dashboard")
    if request.user.rol in {"ADMIN", "ADMIN_OP"} and not _usuario_puede_gestionar_sucursal(
        request.user, cita.sucursal_id
    ):
        messages.error(request, "No tienes permiso para acceder a esta sucursal.")
        return redirect("dashboard")

    fecha_cita = cita.fecha_hora
    if fecha_cita:
        if timezone.is_aware(fecha_cita):
            fecha_cita = timezone.localtime(fecha_cita)
    else:
        fecha_cita = datetime.combine(cita.fecha_solicitada, time.min)
        if timezone.is_naive(fecha_cita):
            fecha_cita = timezone.make_aware(
                fecha_cita, timezone.get_current_timezone()
            )

    historial = getattr(cita, "historial_medico", None)

    if not historial and fecha_cita:
        historial = (
            HistorialMedico.objects.filter(
                paciente=cita.paciente,
                cita__isnull=True,
                fecha__date=fecha_cita.date(),
            )
            .order_by("-fecha")
            .first()
        )

    informe_directo = bool(historial and getattr(historial, "cita_id", None) == cita.id)

    return render(
        request,
        "core/detalle_cita.html",
        {"cita": cita, "historial": historial, "informe_directo": informe_directo},
    )


@login_required
def agendar_cita_admin(request):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para agendar citas.")
        return redirect("dashboard")

    mascotas = Paciente.objects.all().order_by("nombre")
    sucursales_disponibles = list(_sucursales_para_usuario(request.user))
    sucursal_seleccionada = None
    if not request.user.is_superuser:
        sucursal_seleccionada = getattr(request.user, "sucursal", None)
        if sucursal_seleccionada is None:
            messages.warning(
                request,
                "Asigna una sucursal a tu perfil para poder programar citas.",
            )
    elif sucursales_disponibles:
        sucursal_seleccionada = sucursales_disponibles[0]

    veterinarios = (
        _veterinarios_activos(sucursal_seleccionada)
        if sucursal_seleccionada is not None
        else _veterinarios_activos()
    )
    paciente_seleccionado = None

    if request.method == "POST":
        paciente_id = request.POST.get("paciente")
        veterinario_id = request.POST.get("veterinario")
        fecha_hora_raw = request.POST.get("fecha_hora")
        notas = request.POST.get("notas", "").strip()
        sucursal_id = request.POST.get("sucursal")

        paciente = get_object_or_404(Paciente, id=paciente_id)

        if request.user.is_superuser:
            sucursal = get_object_or_404(Sucursal, id=sucursal_id)
        else:
            sucursal = getattr(request.user, "sucursal", None)
            if sucursal is None or (
                sucursal_id and str(sucursal.id) != str(sucursal_id)
            ):
                messages.error(
                    request,
                    "No tienes permiso para asignar citas en esa sucursal.",
                )
                sucursal = None

        if sucursal is None:
            veterinario = None
        else:
            sucursal_seleccionada = sucursal
            veterinarios = _veterinarios_activos(sucursal)
            veterinario = get_object_or_404(
                veterinarios,
                id=veterinario_id,
            )

        try:
            fecha_hora_dt = datetime.fromisoformat(fecha_hora_raw)
        except (TypeError, ValueError):
            messages.error(request, "Selecciona una fecha y hora válidas.")
        else:
            if sucursal is None:
                pass
            elif timezone.is_naive(fecha_hora_dt):
                fecha_hora_dt = timezone.make_aware(
                    fecha_hora_dt, timezone.get_current_timezone()
                )

            if sucursal is None:
                messages.error(
                    request,
                    "Debes seleccionar una sucursal válida para la cita.",
                )
            elif fecha_hora_dt < timezone.now():
                messages.error(request, "No puedes programar una cita en el pasado.")
            else:
                Cita.objects.create(
                    paciente=paciente,
                    veterinario=veterinario,
                    fecha_solicitada=fecha_hora_dt.date(),
                    fecha_hora=fecha_hora_dt,
                    notas=notas,
                    sucursal=sucursal,
                    estado="programada",
                )
                nombre_vet = veterinario.get_full_name() or veterinario.username
                messages.success(
                    request,
                    f"Cita para {paciente.nombre} asignada a {nombre_vet} ✅",
                )
                return redirect("dashboard")

        paciente_seleccionado = paciente

    return render(
        request,
        "core/agendar_cita_admin.html",
        {
            "mascotas": mascotas,
            "veterinarios": veterinarios,
            "paciente_seleccionado": paciente_seleccionado,
            "sucursales": sucursales_disponibles,
            "sucursal_seleccionada": sucursal_seleccionada,
            "es_superadmin": request.user.is_superuser,
        },
    )


@login_required
def crear_propietario_admin(request):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para esta acción.")
        return redirect("dashboard")

    form_data = request.POST if request.method == "POST" else {}

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        telefono = request.POST.get("telefono")
        direccion = request.POST.get("direccion")
        password = request.POST.get("password")

        if User.objects.filter(username=username).exists():
            messages.error(request, "El usuario ya existe.")
        else:
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
                rol="OWNER",
            )
            user.telefono = telefono or ""
            user.direccion = direccion or ""
            user.save(update_fields=["telefono", "direccion"])

            propietario, _ = Propietario.objects.get_or_create(user=user)
            campos_actualizados = []
            if telefono is not None:
                propietario.telefono = telefono
                campos_actualizados.append("telefono")
            if direccion is not None:
                propietario.direccion = direccion
                campos_actualizados.append("direccion")
            if campos_actualizados:
                propietario.save(update_fields=campos_actualizados)

            messages.success(request, "Propietario creado correctamente ✅")
            return redirect("dashboard")

    return render(
        request,
        "core/crear_propietario_admin.html",
        {"form_data": form_data},
    )


@login_required
def crear_mascota_admin(request):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para esta acción.")
        return redirect("dashboard")

    propietarios = Propietario.objects.all()
    form_data = request.POST if request.method == "POST" else {}

    foto_subida = None

    if request.method == "POST":
        has_error = False
        nombre = request.POST.get("nombre")
        especie = request.POST.get("especie")
        raza = request.POST.get("raza")
        sexo = request.POST.get("sexo")
        fecha_nacimiento = request.POST.get("fecha_nacimiento")
        propietario_id = request.POST.get("propietario")
        foto_subida = request.FILES.get("foto")

        propietario = None
        if propietario_id:
            propietario = Propietario.objects.filter(id=propietario_id).first()

        if propietario is None:
            messages.error(request, "Debes seleccionar un propietario válido.")
            has_error = True

        fecha_obj = None
        if fecha_nacimiento:
            try:
                fecha_obj = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "La fecha de nacimiento no es válida.")
                has_error = True
        else:
            messages.error(request, "Debes indicar la fecha de nacimiento.")
            has_error = True

        if not has_error:
            Paciente.objects.create(
                nombre=nombre,
                especie=especie,
                raza=raza,
                sexo=sexo,
                fecha_nacimiento=fecha_obj,
                propietario=propietario,
                foto=foto_subida,
            )
            messages.success(request, "Mascota creada correctamente ✅")
            return redirect("dashboard")

    return render(
        request,
        "core/crear_mascota_admin.html",
        {
            "propietarios": propietarios,
            "form_data": form_data,
            "foto_subida": foto_subida,
        },
    )


@login_required
def buscar_propietarios(request):
    if request.user.rol not in {"ADMIN", "ADMIN_OP"}:
        messages.error(request, "No tienes permiso para esta acción.")
        return redirect("dashboard")

    q = request.GET.get("q", "")
    resultados = []
    total_encontrados = 0

    if q:
        resultados = (
            Propietario.objects.select_related("user")
            .annotate(total_mascotas=Count("paciente", distinct=True))
            .filter(
                Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(user__username__icontains=q)
                | Q(telefono__icontains=q)
                | Q(direccion__icontains=q)
                | Q(ciudad__icontains=q)
            )
            .order_by("user__first_name", "user__last_name")
        )
        total_encontrados = resultados.count()

    return render(
        request,
        "core/buscar_propietarios.html",
        {
            "resultados": resultados,
            "query": q,
            "total_encontrados": total_encontrados,
        },
    )


@login_required
def detalle_propietario(request, propietario_id):
    if request.user.rol not in {"ADMIN", "ADMIN_OP"}:
        messages.error(request, "No tienes permiso para esta acción.")
        return redirect("dashboard")

    propietario = get_object_or_404(Propietario, id=propietario_id)
    mascotas = Paciente.objects.filter(propietario=propietario)
    citas = Cita.objects.filter(paciente__in=mascotas)
    if not request.user.is_superuser:
        citas = citas.filter(sucursal_id=getattr(request.user, "sucursal_id", None))
        mascotas = mascotas.filter(cita__sucursal_id=getattr(request.user, "sucursal_id", None)).distinct()
    citas = citas.order_by("-fecha_solicitada", "-fecha_hora")
    citas_pendientes = citas.filter(estado="pendiente").order_by(
        "fecha_solicitada", "fecha_hora"
    )
    informes = HistorialMedico.objects.filter(paciente__in=mascotas)
    if not request.user.is_superuser:
        informes = informes.filter(
            paciente__cita__sucursal_id=getattr(request.user, "sucursal_id", None)
        ).distinct()

    return render(
        request,
        "core/detalle_propietario.html",
        {
            "propietario": propietario,
            "mascotas": mascotas,
            "citas": citas,
            "citas_pendientes": citas_pendientes,
            "informes": informes,
        },
    )


@login_required
def gestionar_veterinarios(request):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para gestionar veterinarios.")
        return redirect("dashboard")

    usuarios_no_vet = User.objects.exclude(rol="VET")
    if not request.user.is_superuser:
        sucursal_admin = getattr(request.user, "sucursal", None)
        if sucursal_admin is None:
            messages.warning(
                request,
                "Asigna una sucursal a tu perfil para administrar veterinarios.",
            )
            usuarios_no_vet = usuarios_no_vet.none()
        else:
            usuarios_no_vet = usuarios_no_vet.filter(
                Q(sucursal=sucursal_admin) | Q(sucursal__isnull=True)
            )

    sucursales = list(_sucursales_para_usuario(request.user))

    if request.method == "POST":
        user_id = request.POST.get("usuario")
        sucursal_id = request.POST.get("sucursal")
        usuario = get_object_or_404(User, id=user_id)

        if request.user.is_superuser:
            sucursal = get_object_or_404(Sucursal, id=sucursal_id)
        else:
            sucursal = getattr(request.user, "sucursal", None)
            if sucursal is None or (
                sucursal_id and str(sucursal.id) != str(sucursal_id)
            ):
                messages.error(
                    request,
                    "No tienes permiso para asignar usuarios a esa sucursal.",
                )
                return redirect("gestionar_veterinarios")

        usuario.rol = "VET"
        usuario.sucursal = sucursal
        usuario.save(update_fields=["rol", "sucursal"])
        messages.success(
            request,
            f"{usuario.get_full_name() or usuario.username} ahora es Veterinario en {sucursal.nombre} ✅",
        )
        return redirect("gestionar_veterinarios")

    return render(
        request,
        "core/asignar_veterinario_admin.html",
        {"usuarios": usuarios_no_vet, "sucursales": sucursales, "es_superadmin": request.user.is_superuser},
    )


@login_required
def inventario_farmacos_admin(request):
    usuario = request.user
    if usuario.rol != "ADMIN" and not usuario.is_superuser:
        messages.error(request, "Acceso exclusivo para administradores.")
        return redirect("dashboard")

    sucursales_queryset = _sucursales_para_usuario(usuario)
    sucursales_disponibles = list(sucursales_queryset)
    if usuario.is_superuser:
        sucursales_para_formulario = Sucursal.objects.all()
    else:
        sucursales_para_formulario = Sucursal.objects.filter(
            id__in=[s.id for s in sucursales_disponibles]
        )
    sucursales_para_formulario = sucursales_para_formulario.order_by("nombre")

    sucursal_seleccionada = None
    sucursal_param = request.GET.get("sucursal")
    if sucursal_param:
        sucursal_seleccionada = Sucursal.objects.filter(id=sucursal_param).first()
        if sucursal_seleccionada and not _usuario_puede_gestionar_sucursal(
            usuario, sucursal_seleccionada.id
        ):
            messages.error(
                request,
                "No tienes permisos para administrar el inventario de esa sucursal.",
            )
            return redirect("inventario_farmacos_admin")
    elif getattr(usuario, "sucursal_id", None):
        sucursal_seleccionada = Sucursal.objects.filter(id=usuario.sucursal_id).first()
    elif sucursales_disponibles:
        sucursal_seleccionada = sucursales_disponibles[0]

    farmaco_en_edicion = None
    editar_form = None
    crear_form = FarmacoForm(
        sucursales=sucursales_para_formulario,
        initial={"sucursal": sucursal_seleccionada} if sucursal_seleccionada else {},
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "crear":
            form = FarmacoForm(request.POST, sucursales=sucursales_para_formulario)
            if form.is_valid():
                farmaco = form.save()
                messages.success(
                    request,
                    "Fármaco registrado en el inventario de {}.".format(
                        farmaco.sucursal.nombre
                    ),
                )
                return redirect(
                    f"{reverse('inventario_farmacos_admin')}?sucursal={farmaco.sucursal_id}"
                )
            crear_form = form
            sucursal_data = form.cleaned_data.get("sucursal") if form.is_valid() else None
            if not sucursal_data:
                sucursal_id = form.data.get("sucursal")
                sucursal_data = (
                    Sucursal.objects.filter(id=sucursal_id).first()
                    if sucursal_id
                    else None
                )
            if sucursal_data:
                sucursal_seleccionada = sucursal_data

        elif action == "actualizar":
            farmaco_id = request.POST.get("farmaco_id")
            farmaco = get_object_or_404(Farmaco, id=farmaco_id)
            if not _usuario_puede_gestionar_sucursal(usuario, farmaco.sucursal_id):
                messages.error(
                    request,
                    "No tienes permisos para modificar este inventario.",
                )
                return redirect("inventario_farmacos_admin")

            form = FarmacoForm(
                request.POST,
                instance=farmaco,
                sucursales=sucursales_para_formulario,
            )
            if form.is_valid():
                farmaco_actualizado = form.save()
                messages.success(
                    request,
                    "Inventario actualizado correctamente para {}.".format(
                        farmaco_actualizado.nombre
                    ),
                )
                return redirect(
                    f"{reverse('inventario_farmacos_admin')}?sucursal={farmaco_actualizado.sucursal_id}"
                )
            farmaco_en_edicion = farmaco
            editar_form = form
            sucursal_seleccionada = farmaco.sucursal

        elif action == "eliminar":
            farmaco_id = request.POST.get("farmaco_id")
            farmaco = get_object_or_404(Farmaco, id=farmaco_id)
            if not _usuario_puede_gestionar_sucursal(usuario, farmaco.sucursal_id):
                messages.error(
                    request,
                    "No tienes permisos para eliminar este fármaco.",
                )
            else:
                sucursal_id = farmaco.sucursal_id
                nombre = farmaco.nombre
                farmaco.delete()
                messages.success(
                    request,
                    f"{nombre} eliminado del inventario.",
                )
                return redirect(
                    f"{reverse('inventario_farmacos_admin')}?sucursal={sucursal_id}"
                )
        else:
            messages.error(request, "Acción no reconocida para el inventario.")

    editar_param = request.GET.get("editar")
    if request.method == "GET" and editar_param and editar_form is None:
        farmaco_en_edicion = get_object_or_404(Farmaco, id=editar_param)
        if not _usuario_puede_gestionar_sucursal(
            usuario, farmaco_en_edicion.sucursal_id
        ):
            messages.error(
                request,
                "No tienes permisos para modificar este inventario.",
            )
            return redirect("inventario_farmacos_admin")
        editar_form = FarmacoForm(
            instance=farmaco_en_edicion,
            sucursales=sucursales_para_formulario,
        )
        sucursal_seleccionada = farmaco_en_edicion.sucursal

    if sucursal_seleccionada:
        inventario = _inventario_por_sucursal(sucursal_seleccionada)
        farmacos = inventario["farmacos"]
        resumen_inventario = inventario["resumen"]
    else:
        farmacos = []
        resumen_inventario = None

    contexto = {
        "sucursales": sucursales_para_formulario,
        "sucursal_seleccionada": sucursal_seleccionada,
        "farmacos": farmacos,
        "crear_form": crear_form,
        "farmaco_en_edicion": farmaco_en_edicion,
        "editar_form": editar_form,
        "resumen_inventario": resumen_inventario,
    }

    return render(request, "core/inventario_farmacos_admin.html", contexto)


@login_required
def dashboard_veterinarios(request):
    if request.user.rol != "ADMIN":
        return redirect("dashboard")

    veterinarios = _filtrar_por_sucursal(
        User.objects.filter(rol="VET")
        .select_related("sucursal")
        .order_by("first_name", "last_name"),
        request.user,
    )

    citas_base = _filtrar_por_sucursal(Cita.objects.all(), request.user)

    total_pendientes = citas_base.filter(estado="pendiente").count()
    total_programadas = citas_base.filter(estado="programada").count()
    total_atendidas = citas_base.filter(estado="atendida").count()
    total_canceladas = citas_base.filter(estado="cancelada").count()

    citas_en_proceso = total_pendientes + total_programadas
    tasa_cumplimiento = 0
    if total_programadas + total_atendidas:
        tasa_cumplimiento = round(
            (total_atendidas / (total_programadas + total_atendidas)) * 100
        )

    ahora = timezone.now()
    fin_semana = ahora + timedelta(days=7)

    citas_equipo_semana = (
        citas_base.filter(
            estado="programada",
            fecha_hora__isnull=False,
            fecha_hora__gte=ahora,
            fecha_hora__lte=fin_semana,
        )
        .select_related("paciente", "veterinario", "paciente__propietario__user")
        .order_by("fecha_hora")
    )

    proximos_turnos_equipo = citas_equipo_semana[:6]
    solicitudes_recientes = (
        citas_base.filter(estado="pendiente")
        .select_related("paciente", "paciente__propietario__user")
        .order_by("fecha_solicitada")[:5]
    )

    total_semana = citas_equipo_semana.count()
    citas_hoy_total = (
        citas_base.filter(
            estado="programada",
            fecha_hora__date=ahora.date(),
        )
        .exclude(fecha_hora__isnull=True)
        .count()
    )
    citas_sin_horario_total = citas_base.filter(
        estado="programada", fecha_hora__isnull=True
    ).count()

    porcentaje_semana = 0
    if total_programadas:
        porcentaje_semana = min(100, round((total_semana / total_programadas) * 100))

    resumen_global = {
        "total_veterinarios": veterinarios.count(),
        "citas_pendientes": total_pendientes,
        "citas_programadas": total_programadas,
        "citas_atendidas": total_atendidas,
        "citas_canceladas": total_canceladas,
        "citas_en_proceso": citas_en_proceso,
        "tasa_cumplimiento": tasa_cumplimiento,
        "citas_semana": total_semana,
        "citas_hoy": citas_hoy_total,
        "citas_sin_horario": citas_sin_horario_total,
        "porcentaje_semana": porcentaje_semana,
    }

    vet_stats = []
    for vet in veterinarios:
        citas_totales = citas_base.filter(veterinario=vet).count()
        citas_programadas = citas_base.filter(
            veterinario=vet, estado="programada"
        ).count()
        citas_pendientes = citas_base.filter(
            veterinario=vet, estado="pendiente"
        ).count()
        citas_atendidas = citas_base.filter(
            veterinario=vet, estado="atendida"
        ).count()
        citas_canceladas = citas_base.filter(
            veterinario=vet, estado="cancelada"
        ).count()

        proximas_confirmadas = (
            citas_base.filter(
                veterinario=vet, estado="programada", fecha_hora__isnull=False
            )
            .order_by("fecha_hora")[:5]
        )
        proximas_sin_horario = (
            citas_base.filter(
                veterinario=vet, estado="programada", fecha_hora__isnull=True
            )
            .order_by("fecha_solicitada")[:5]
        )
        proximas_citas = list(chain(proximas_confirmadas, proximas_sin_horario))[:5]

        nombre_completo = vet.get_full_name() or vet.username
        iniciales = "".join(parte[0] for parte in nombre_completo.split() if parte)[:2]
        if not iniciales:
            iniciales = (vet.username[:2] or "VF").upper()
        else:
            iniciales = iniciales.upper()

        citas_en_proceso = citas_programadas + citas_pendientes
        tasa_atencion = 0
        if citas_programadas + citas_atendidas:
            tasa_atencion = round(
                (citas_atendidas / (citas_programadas + citas_atendidas)) * 100
            )

        citas_semana_vet = citas_base.filter(
            veterinario=vet,
            estado="programada",
            fecha_hora__isnull=False,
            fecha_hora__gte=ahora,
            fecha_hora__lte=fin_semana,
        ).count()

        vet_stats.append(
            {
                "veterinario": vet,
                "citas_totales": citas_totales,
                "citas_programadas": citas_programadas,
                "citas_pendientes": citas_pendientes,
                "citas_atendidas": citas_atendidas,
                "citas_canceladas": citas_canceladas,
                "citas_en_proceso": citas_en_proceso,
                "citas_semana": citas_semana_vet,
                "proximas_citas": proximas_citas,
                "tasa_atencion": tasa_atencion,
                "iniciales": iniciales,
                "nombre_completo": nombre_completo,
                "sucursal": vet.sucursal,
                "sucursal_nombre": vet.sucursal.nombre if vet.sucursal else "",
            }
        )

    max_carga = max((stat["citas_en_proceso"] for stat in vet_stats), default=0)
    for stat in vet_stats:
        porcentaje_carga = 0
        if max_carga:
            porcentaje_carga = round((stat["citas_en_proceso"] / max_carga) * 100)
        stat["porcentaje_carga"] = porcentaje_carga

    return render(
        request,
        "core/dashboard_veterinarios.html",
        {
            "vet_stats": vet_stats,
            "resumen": resumen_global,
            "proximos_turnos_equipo": proximos_turnos_equipo,
            "solicitudes_recientes": solicitudes_recientes,
        },
    )


@login_required
def inventario_farmacos_veterinario(request):
    if request.user.rol != "VET":
        messages.error(request, "Acceso exclusivo para el equipo veterinario.")
        return redirect("dashboard")

    sucursal = getattr(request.user, "sucursal", None)
    if sucursal is None:
        messages.warning(
            request,
            "Tu perfil no tiene una sucursal asociada. Solicita al equipo administrativo que actualice tu información para consultar el inventario farmacológico.",
        )
        contexto = {
            "sucursal": None,
            "inventario": [],
            "totales": {
                "total_items": 0,
                "total_stock": 0,
                "ultima_actualizacion": None,
            },
            "criticos": [],
        }
        return render(request, "core/inventario_farmacos_vet.html", contexto)

    inventario = _inventario_por_sucursal(sucursal)
    resumen = inventario["resumen"]
    farmacos = inventario["farmacos"]

    query = request.GET.get("q", "").strip()
    categoria = request.GET.get("categoria", "").strip()

    farmacos_filtrados = farmacos
    if query:
        termino = query.lower()
        farmacos_filtrados = [
            farmaco
            for farmaco in farmacos_filtrados
            if termino in (farmaco.nombre or "").lower()
            or termino in (farmaco.descripcion or "").lower()
        ]

    if categoria:
        farmacos_filtrados = [
            farmaco for farmaco in farmacos_filtrados if farmaco.categoria == categoria
        ]

    categorias_filtradas = []
    for codigo, etiqueta in Farmaco.Categoria.choices:
        items = [farmaco for farmaco in farmacos_filtrados if farmaco.categoria == codigo]
        if items:
            categorias_filtradas.append(
                {
                    "codigo": codigo,
                    "nombre": etiqueta,
                    "total_items": len(items),
                    "total_stock": sum(item.stock for item in items),
                    "items": items,
                }
            )

    contexto = {
        "sucursal": sucursal,
        "inventario": categorias_filtradas,
        "totales": {
            "total_items": len(farmacos_filtrados),
            "total_stock": sum(item.stock for item in farmacos_filtrados),
            "ultima_actualizacion": resumen["ultima_actualizacion"],
        },
        "criticos": [farmaco for farmaco in farmacos_filtrados if farmaco.stock <= 5],
        "categorias_disponibles": Farmaco.Categoria.choices,
        "filtros": {"q": query, "categoria": categoria},
        "hay_filtros": bool(query or categoria),
    }

    return render(request, "core/inventario_farmacos_vet.html", contexto)


@login_required
def dashboard_veterinarios_indicadores(request):
    if request.user.rol not in {"ADMIN", "ADMIN_OP", "VET"}:
        messages.error(request, "No tienes permiso para acceder a los indicadores estratégicos.")
        return redirect("dashboard")

    ahora = timezone.now()
    inicio_periodo = (ahora - timedelta(days=29)).date()
    fin_periodo = ahora.date()

    sucursal_activa = None
    if not request.user.is_superuser and request.user.rol in _roles_con_sucursal():
        sucursal_activa = getattr(request.user, "sucursal", None)

    citas_totales = _filtrar_por_sucursal(Cita.objects.all(), request.user)

    citas_periodo = (
        citas_totales.filter(fecha_solicitada__gte=inicio_periodo)
        .select_related("paciente", "paciente__propietario__user", "veterinario")
        .order_by("-fecha_solicitada")
    )

    total_periodo = citas_periodo.count()
    total_pendientes = citas_periodo.filter(estado="pendiente").count()
    total_programadas = citas_periodo.filter(estado="programada").count()
    total_atendidas = citas_periodo.filter(estado="atendida").count()
    total_canceladas = citas_periodo.filter(estado="cancelada").count()

    tasa_resolucion = 0
    if total_periodo:
        tasa_resolucion = round((total_atendidas / total_periodo) * 100, 1)

    tasa_confirmacion = 0
    if total_programadas + total_atendidas:
        tasa_confirmacion = round(
            (total_atendidas / (total_programadas + total_atendidas)) * 100, 1
        )

    tasa_cancelacion = 0
    if total_periodo:
        tasa_cancelacion = round((total_canceladas / total_periodo) * 100, 1)

    tiempos_confirmacion = []
    for cita in citas_periodo.filter(fecha_hora__isnull=False):
        fecha_confirmada = timezone.localtime(cita.fecha_hora).date()
        delta = (fecha_confirmada - cita.fecha_solicitada).days
        if delta >= 0:
            tiempos_confirmacion.append(delta)

    promedio_confirmacion = 0
    if tiempos_confirmacion:
        promedio_confirmacion = round(sum(tiempos_confirmacion) / len(tiempos_confirmacion), 1)

    serie_diaria = []
    for offset in range(6, -1, -1):
        dia = ahora.date() - timedelta(days=offset)
        serie_diaria.append(
            {
                "fecha": dia,
                "label": dia.strftime("%d/%m"),
                "solicitadas": citas_totales.filter(fecha_solicitada=dia).count(),
                "programadas": citas_totales.filter(
                    estado="programada", fecha_hora__date=dia
                ).count(),
                "atendidas": citas_totales.filter(
                    estado="atendida", fecha_hora__date=dia
                ).count(),
                "canceladas": citas_totales.filter(
                    estado="cancelada", fecha_hora__date=dia
                ).count(),
            }
        )

    tipos_mas_demandados_qs = (
        citas_periodo.values("tipo")
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )

    tipo_labels = dict(Cita.TIPOS)
    tipos_mas_demandados = [
        {"tipo": tipo_labels.get(item["tipo"], item["tipo"]), "total": item["total"]}
        for item in tipos_mas_demandados_qs
    ]

    veterinarios_performance = (
        citas_periodo.exclude(veterinario__isnull=True)
        .values(
            "veterinario__id",
            "veterinario__first_name",
            "veterinario__last_name",
        )
        .annotate(
            total=Count("id"),
            atendidas=Count("id", filter=Q(estado="atendida")),
            programadas=Count("id", filter=Q(estado="programada")),
            pendientes=Count("id", filter=Q(estado="pendiente")),
        )
        .order_by("-atendidas", "-total")[:6]
    )

    propietarios_top = (
        citas_periodo.values(
            "paciente__propietario__user__first_name",
            "paciente__propietario__user__last_name",
        )
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )

    agenda_semana = (
        citas_totales.filter(
            estado="programada",
            fecha_hora__isnull=False,
            fecha_hora__date__gte=fin_periodo,
            fecha_hora__date__lte=(fin_periodo + timedelta(days=6)),
        )
        .select_related("paciente", "paciente__propietario__user", "veterinario")
        .order_by("fecha_hora")[:6]
    )

    citas_sin_veterinario = citas_periodo.filter(veterinario__isnull=True).count()

    contexto = {
        "resumen": {
            "total": total_periodo,
            "pendientes": total_pendientes,
            "programadas": total_programadas,
            "atendidas": total_atendidas,
            "canceladas": total_canceladas,
            "tasa_resolucion": tasa_resolucion,
            "tasa_confirmacion": tasa_confirmacion,
            "tasa_cancelacion": tasa_cancelacion,
            "promedio_confirmacion": promedio_confirmacion,
            "sin_veterinario": citas_sin_veterinario,
            "inicio_periodo": inicio_periodo,
            "fin_periodo": fin_periodo,
        },
        "serie_diaria": serie_diaria,
        "tipos_mas_demandados": tipos_mas_demandados,
        "veterinarios_performance": veterinarios_performance,
        "propietarios_top": propietarios_top,
        "agenda_semana": agenda_semana,
        "sucursal_activa": sucursal_activa,
    }

    return render(
        request,
        "core/dashboard_veterinarios_indicadores.html",
        contexto,
    )


@login_required
def historial_medico_vet(request):
    if request.user.rol not in {"ADMIN", "VET"}:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect("dashboard")

    query = request.GET.get("q", "")
    fecha_desde = request.GET.get("desde", "")
    fecha_hasta = request.GET.get("hasta", "")

    historiales = HistorialMedico.objects.select_related(
        "paciente",
        "paciente__propietario__user",
        "veterinario",
        "cita",
    )

    if query:
        historiales = historiales.filter(
            Q(paciente__nombre__icontains=query)
            | Q(paciente__propietario__user__first_name__icontains=query)
            | Q(paciente__propietario__user__last_name__icontains=query)
            | Q(diagnostico__icontains=query)
        )

    if fecha_desde:
        historiales = historiales.filter(fecha__date__gte=fecha_desde)
    if fecha_hasta:
        historiales = historiales.filter(fecha__date__lte=fecha_hasta)

    historiales = historiales.order_by("-fecha")

    total_historiales = historiales.count()
    ahora = timezone.now()
    hace_7_dias = ahora - timedelta(days=7)
    hace_30_dias = ahora - timedelta(days=30)

    historiales_semana = historiales.filter(fecha__gte=hace_7_dias).count()
    historiales_mes = historiales.filter(fecha__gte=hace_30_dias).count()
    historiales_sin_cita = historiales.filter(cita__isnull=True).count()
    pacientes_activos = (
        historiales.values("paciente_id").distinct().count()
    )
    veterinarios_activos = (
        historiales.exclude(veterinario__isnull=True)
        .values("veterinario_id")
        .distinct()
        .count()
    )

    ultima_actualizacion = historiales.first().fecha if total_historiales else None

    especies_destacadas = (
        historiales.values("paciente__especie")
        .annotate(total=Count("id"))
        .order_by("-total")[:4]
    )

    profesionales_destacados = (
        historiales.exclude(veterinario__isnull=True)
        .values(
            "veterinario__id",
            "veterinario__first_name",
            "veterinario__last_name",
        )
        .annotate(total=Count("id"))
        .order_by("-total")[:6]
    )

    ultimos_historiales = historiales[:5]

    contexto = {
        "historiales": historiales,
        "query": query,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "resumen": {
            "total": total_historiales,
            "semana": historiales_semana,
            "mes": historiales_mes,
            "sin_cita": historiales_sin_cita,
            "pacientes": pacientes_activos,
            "veterinarios": veterinarios_activos,
            "ultima_actualizacion": ultima_actualizacion,
        },
        "especies_destacadas": especies_destacadas,
        "profesionales_destacados": profesionales_destacados,
        "ultimos_historiales": ultimos_historiales,
    }

    return render(request, "core/historial_medico_vet.html", contexto)


@login_required
def detalle_historial(request, historial_id):
    historial = get_object_or_404(HistorialMedico, id=historial_id)
    return render(request, "core/detalle_historial.html", {"historial": historial})


# ----------------------------
# Gestión de productos
# ----------------------------


@login_required
def admin_productos_list(request):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para gestionar la tienda.")
        return redirect("dashboard")

    if not _producto_table_available():
        messages.warning(
            request,
            "La tienda aún no está lista. Ejecuta las migraciones para crear la tabla de productos.",
        )
        productos = Producto.objects.none()
    else:
        productos = Producto.objects.all().order_by("-actualizado")
    return render(request, "core/admin_productos_list.html", {"productos": productos})


@login_required
def admin_producto_crear(request):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para gestionar la tienda.")
        return redirect("dashboard")

    if not _producto_table_available():
        messages.error(
            request,
            "Debes ejecutar las migraciones antes de crear productos en la tienda.",
        )
        return redirect("admin_productos_list")

    if request.method == "POST":
        form = ProductoForm(request.POST, request.FILES)
        if form.is_valid():
            producto = form.save()
            messages.success(
                request, f"Producto {producto.nombre} creado correctamente ✅"
            )
            return redirect("admin_productos_list")
    else:
        form = ProductoForm()

    return render(
        request,
        "core/admin_producto_form.html",
        {"form": form, "titulo": "Nuevo producto"},
    )


@login_required
def admin_producto_editar(request, producto_id):
    if request.user.rol != "ADMIN":
        messages.error(request, "No tienes permiso para gestionar la tienda.")
        return redirect("dashboard")

    if not _producto_table_available():
        messages.error(
            request,
            "Debes ejecutar las migraciones antes de editar productos en la tienda.",
        )
        return redirect("admin_productos_list")

    producto = get_object_or_404(Producto, id=producto_id)

    if request.method == "POST":
        form = ProductoForm(request.POST, request.FILES, instance=producto)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Producto {producto.nombre} actualizado correctamente ✅"
            )
            return redirect("admin_productos_list")
    else:
        form = ProductoForm(instance=producto)

    return render(
        request,
        "core/admin_producto_form.html",
        {"form": form, "titulo": f"Editar {producto.nombre}", "producto": producto},
    )


# ----------------------------
# Autenticación
# ----------------------------

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard")
        messages.error(request, "Usuario o contraseña incorrectos.")
    return render(request, "core/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


def registro_propietario(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        telefono = request.POST.get("telefono")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")

        if password1 != password2:
            messages.error(request, "Las contraseñas no coinciden.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "El usuario ya existe.")
        else:
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password1,
                rol="OWNER",
            )
            Propietario.objects.create(user=user, telefono=telefono)
            messages.success(
                request, "Registro exitoso. Ahora puedes iniciar sesión."
            )
            return redirect("login")

    return render(request, "core/registro_propietario.html")

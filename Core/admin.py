from django.contrib import admin

from .forms import UserAdminForm
from .models import (
    Cita,
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

# ----------------------------
# Admin de User
# ----------------------------
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    form = UserAdminForm
    add_form = UserAdminForm
    list_display = ("username", "rol", "sucursal", "email", "is_active", "especialidad")
    list_filter = ("rol", "sucursal", "is_active", "activo")
    search_fields = ("username", "email", "rol", "sucursal__nombre")
    readonly_fields = ("last_login", "date_joined")
    fieldsets = (
        (
            "Datos de usuario",
            {
                "fields": (
                    "username",
                    "password",
                    "rol",
                    "sucursal",
                    "email",
                    "telefono",
                    "direccion",
                    "activo",
                    "avatar",
                    "especialidad",
                )
            },
        ),
        ("Fechas importantes", {"fields": ("last_login", "date_joined")}),
        ("Permisos", {"fields": ("is_staff", "is_superuser")}),
    )


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ("nombre", "direccion", "ciudad", "telefono")
    search_fields = ("nombre", "direccion", "ciudad")
    fields = ("nombre", "direccion", "ciudad", "telefono", "imagen")

# ----------------------------
# Admin de Propietario
# ----------------------------
@admin.register(Propietario)
class PropietarioAdmin(admin.ModelAdmin):
    list_display = ("user", "telefono", "ciudad")
    search_fields = ("user__username", "user__email", "ciudad")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Si el usuario logueado es propietario, ve solo su registro
        if request.user.rol == "OWNER":
            return qs.filter(user=request.user)
        return qs

# ----------------------------
# Admin de Paciente
# ----------------------------
@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "especie", "raza", "propietario")
    search_fields = ("nombre", "especie", "raza", "propietario__user__username")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.rol == "OWNER":
            return qs.filter(propietario__user=request.user)
        return qs

# ----------------------------
# Admin de Cita
# ----------------------------
@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = (
        "paciente",
        "sucursal",
        "veterinario",
        "fecha_solicitada",
        "fecha_hora",
        "tipo",
        "estado",
    )
    list_filter = ("sucursal", "estado", "tipo")
    search_fields = (
        "paciente__nombre",
        "veterinario__username",
        "sucursal__nombre",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.rol == "VET":
            return qs.filter(veterinario=request.user)
        elif request.user.rol == "OWNER":
            return qs.filter(paciente__propietario__user=request.user)
        return qs

# ----------------------------
# Admin de Historial Médico
# ----------------------------
@admin.register(HistorialMedico)
class HistorialMedicoAdmin(admin.ModelAdmin):
    list_display = ("paciente", "cita", "veterinario", "fecha", "diagnostico")
    search_fields = ("paciente__nombre", "veterinario__username", "diagnostico")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.rol == "VET":
            return qs.filter(veterinario=request.user)
        elif request.user.rol == "OWNER":
            return qs.filter(paciente__propietario__user=request.user)
        return qs


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "categoria",
        "precio",
        "telefono_contacto",
        "disponible",
        "actualizado",
    )
    list_filter = ("categoria", "disponible")
    search_fields = ("nombre", "descripcion")


@admin.register(Farmaco)
class FarmacoAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "sucursal",
        "categoria",
        "stock",
        "actualizado",
    )
    list_filter = ("sucursal", "categoria")
    search_fields = ("nombre", "descripcion")
    autocomplete_fields = ("sucursal",)


@admin.register(VacunaRecomendada)
class VacunaRecomendadaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "especie", "edad_recomendada_display", "refuerzo", "orden")
    list_filter = ("especie",)
    search_fields = ("nombre", "descripcion", "refuerzo")
    ordering = ("especie", "orden", "nombre")

    @staticmethod
    def edad_recomendada_display(obj):
        return obj.edad_legible()


@admin.register(VacunaRegistro)
class VacunaRegistroAdmin(admin.ModelAdmin):
    list_display = ("paciente", "vacuna", "fecha_aplicacion", "actualizado")
    list_filter = ("vacuna__especie", "fecha_aplicacion")
    search_fields = ("paciente__nombre", "vacuna__nombre")
    autocomplete_fields = ("paciente", "vacuna")

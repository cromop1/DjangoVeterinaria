from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


# ----------------------------
# Sucursal
# ----------------------------
class Sucursal(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    direccion = models.CharField(max_length=255)
    ciudad = models.CharField(max_length=120, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    imagen = models.ImageField(upload_to="sucursales/", blank=True, null=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

# ----------------------------
# Usuario con rol propio
# ----------------------------
class User(AbstractUser):
    ROLES = (
        ("ADMIN", "Administrador"),
        ("VET", "Veterinario"),
        ("ADMIN_OP", "Administrativo"),
        ("OWNER", "Propietario"),
    )
    rol = models.CharField(max_length=20, choices=ROLES)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    activo = models.BooleanField(default=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    especialidad = models.CharField(max_length=100, blank=True)  # para veterinarios
    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios",
    )

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"

# ----------------------------
# Propietario
# ----------------------------
class Propietario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    notas = models.TextField(blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username

# ----------------------------
# Paciente / Mascota
# ----------------------------
class Paciente(models.Model):
    nombre = models.CharField(max_length=100)
    especie = models.CharField(max_length=50)
    raza = models.CharField(max_length=50, blank=True)
    sexo = models.CharField(max_length=10)
    fecha_nacimiento = models.DateField()
    propietario = models.ForeignKey(Propietario, on_delete=models.CASCADE)
    vacunas = models.TextField(blank=True)
    alergias = models.TextField(blank=True)
    foto = models.ImageField(upload_to="pacientes/", blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.especie})"

# ----------------------------
# Cita
# ----------------------------
class Cita(models.Model):
    ESTADOS = (
        ("pendiente", "Pendiente"),
        ("programada", "Programada"),
        ("atendida", "Atendida"),
        ("cancelada", "Cancelada"),
    )
    TIPOS = (
        ("consulta", "Consulta"),
        ("vacunacion", "Vacunación"),
        ("cirugia", "Cirugía"),
    )
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    veterinario = models.ForeignKey(
        User,
        limit_choices_to={"rol": "VET"},
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        related_name="citas",
    )
    fecha_solicitada = models.DateField(default=timezone.now)
    fecha_hora = models.DateTimeField(blank=True, null=True)
    duracion = models.IntegerField(default=30)  # duración en minutos
    tipo = models.CharField(max_length=50, choices=TIPOS, default="consulta")
    estado = models.CharField(max_length=20, choices=ESTADOS, default="pendiente")
    notas = models.TextField(blank=True)
    farmacos_utilizados = models.ManyToManyField(
        "Farmaco",
        blank=True,
        related_name="citas_utilizadas",
        through="CitaFarmaco",
        through_fields=("cita", "farmaco"),
        help_text="Medicamentos del inventario utilizados durante la atención.",
    )

    def __str__(self):
        veterinario_nombre = (
            self.veterinario.username if self.veterinario else "Sin asignar"
        )
        sucursal_nombre = self.sucursal.nombre if self.sucursal_id else "Sin sucursal"
        if self.fecha_hora:
            fecha_local = self.fecha_hora
            if timezone.is_aware(self.fecha_hora):
                fecha_local = timezone.localtime(self.fecha_hora)
            fecha_texto = fecha_local.strftime("%d/%m/%Y %H:%M")
        else:
            fecha_texto = f"{self.fecha_solicitada.strftime('%d/%m/%Y')} (sin horario)"
        return (
            f"Cita: {self.paciente.nombre} ({self.get_estado_display()}) en {sucursal_nombre} "
            f"con {veterinario_nombre} - {fecha_texto}"
        )

    def telefono_contacto(self) -> str:
        propietario = self.paciente.propietario
        telefono = propietario.telefono or propietario.user.telefono or ""
        telefono = telefono.strip()
        if not telefono:
            return ""
        return "".join(ch for ch in telefono if ch.isdigit())

    def mensaje_whatsapp(self) -> str:
        propietario = self.paciente.propietario.user
        nombre = propietario.get_full_name() or propietario.username
        fecha = self.fecha_solicitada.strftime("%d/%m/%Y")
        return (
            f"Hola {nombre}, te saludamos de Sabueso Feliz. "
            f"¿Podemos coordinar el horario para la cita de {self.paciente.nombre} del {fecha}?"
        )


# ----------------------------
# Inventario farmacológico
# ----------------------------
class Farmaco(models.Model):
    class Categoria(models.TextChoices):
        ANALGESICOS_ANTIINFLAMATORIOS = (
            "analgesicos_antiinflamatorios",
            "Analgésicos y antiinflamatorios",
        )
        ANTIBIOTICOS = ("antibioticos", "Antibióticos")
        ANTIPARASITARIOS_INTERNOS = (
            "antiparasitarios_internos",
            "Antiparasitarios internos",
        )
        ANTIPARASITARIOS_EXTERNOS = (
            "antiparasitarios_externos",
            "Antiparasitarios externos",
        )
        VACUNAS = ("vacunas", "Vacunas")
        ANTIEMETICOS_DIGESTIVOS = (
            "antiemeticos_digestivos",
            "Antieméticos y digestivos",
        )
        SUEROS_SOLUCIONES = (
            "sueros_soluciones",
            "Sueros y soluciones",
        )
        ANTICONVULSIVOS = ("anticonvulsivos", "Anticonvulsivos")
        CORTICOIDES = ("corticoides", "Corticoides")
        ANESTESICOS_SEDANTES = (
            "anestesicos_sedantes",
            "Anestésicos y sedantes",
        )
        ANTISEPTICOS_TOPICOS = (
            "antisepticos_topicos",
            "Antisépticos y tópicos",
        )
        HORMONAS_ENDOCRINOS = (
            "hormonas_endocrinos",
            "Hormonas y tratamientos endocrinos",
        )
        VITAMINAS_SUPLEMENTOS = (
            "vitaminas_suplementos",
            "Vitaminas y suplementos nutricionales",
        )
        OFTALMICOS_OTICOS = (
            "oftalmicos_oticos",
            "Oftálmicos y óticos",
        )
        PRODUCTOS_DERMATOLOGICOS = (
            "productos_dermatologicos",
            "Productos dermatológicos",
        )
        EUTANASIA_EMERGENCIAS = (
            "eutanasia_emergencias",
            "Eutanasia y emergencias",
        )

    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        related_name="farmacos",
    )
    nombre = models.CharField(max_length=150)
    categoria = models.CharField(
        max_length=60,
        choices=Categoria.choices,
    )
    descripcion = models.TextField()
    stock = models.PositiveIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sucursal__nombre", "categoria", "nombre"]
        unique_together = ("sucursal", "nombre")

    def __str__(self):
        return f"{self.nombre} - {self.sucursal.nombre}"


class CitaFarmaco(models.Model):
    cita = models.ForeignKey(
        "Cita",
        on_delete=models.CASCADE,
        related_name="administraciones_farmacos",
    )
    farmaco = models.ForeignKey(
        "Farmaco",
        on_delete=models.PROTECT,
        related_name="administraciones",
    )
    cantidad = models.PositiveIntegerField(default=1)
    registrado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["farmaco__nombre"]
        unique_together = ("cita", "farmaco")

    def __str__(self):
        return f"{self.cita_id} - {self.farmaco.nombre} ({self.cantidad})"


# ----------------------------
# Historial Médico
# ----------------------------
class HistorialMedico(models.Model):
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    veterinario = models.ForeignKey(User, limit_choices_to={"rol": "VET"}, on_delete=models.SET_NULL, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    diagnostico = models.TextField()
    tratamiento = models.TextField()
    notas = models.TextField(blank=True)
    peso = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    temperatura = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    examenes = models.TextField(blank=True)
    imagenes = models.ImageField(upload_to="historial_medico/", blank=True, null=True)
    proximo_control = models.DateField(blank=True, null=True)
    sin_proximo_control = models.BooleanField(default=False)
    cita = models.OneToOneField(
        "Cita",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historial_medico",
    )

    def __str__(self):
        return f"Historial de {self.paciente.nombre} - {self.fecha.strftime('%d/%m/%Y')}"


class Producto(models.Model):
    CATEGORIAS = (
        ("alimentos", "Alimentos"),
        ("medicamentos", "Medicamentos"),
        ("accesorios", "Accesorios"),
    )

    nombre = models.CharField(max_length=150)
    descripcion = models.TextField()
    categoria = models.CharField(max_length=30, choices=CATEGORIAS)
    precio = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    imagen = models.ImageField(upload_to="productos/", blank=True, null=True)
    telefono_contacto = models.CharField(max_length=20, blank=True)
    disponible = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-actualizado"]

    def __str__(self):
        return self.nombre

    @property
    def telefono_whatsapp(self) -> str:
        """Return a digits-only phone number suitable for wa.me links."""
        telefono = (self.telefono_contacto or "").strip()
        return "".join(ch for ch in telefono if ch.isdigit())

    @property
    def mensaje_whatsapp(self) -> str:
        """Default WhatsApp message referencing the product name."""
        return (
            f"Hola! Me interesa el producto '{self.nombre}' de la tienda Sabueso Feliz. "
            "¿Me ayudas con los detalles para concretar la compra?"
        )


class VacunaRecomendada(models.Model):
    ESPECIES = (
        ("canino", "Canino"),
        ("felino", "Felino"),
    )

    UNIDADES_TIEMPO = (
        ("semanas", "Semanas"),
        ("meses", "Meses"),
        ("anios", "Años"),
    )

    nombre = models.CharField(max_length=150)
    especie = models.CharField(max_length=20, choices=ESPECIES)
    descripcion = models.TextField(blank=True)
    edad_recomendada = models.PositiveIntegerField()
    unidad_tiempo = models.CharField(max_length=10, choices=UNIDADES_TIEMPO)
    refuerzo = models.CharField(max_length=150, blank=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["especie", "orden", "nombre"]
        unique_together = ("especie", "nombre")

    def __str__(self):
        return f"{self.nombre} ({self.get_especie_display()})"

    def edad_legible(self) -> str:
        unidad = self.get_unidad_tiempo_display().lower()
        valor = self.edad_recomendada
        if valor == 1 and unidad.endswith("s"):
            unidad = unidad[:-1]
        return f"{valor} {unidad}"


class VacunaRegistro(models.Model):
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.CASCADE,
        related_name="registros_vacunas",
    )
    vacuna = models.ForeignKey(
        VacunaRecomendada,
        on_delete=models.CASCADE,
        related_name="registros",
    )
    fecha_aplicacion = models.DateField()
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha_aplicacion", "-actualizado"]
        unique_together = ("paciente", "vacuna")

    def __str__(self):
        return f"{self.vacuna.nombre} - {self.paciente.nombre} ({self.fecha_aplicacion:%d/%m/%Y})"

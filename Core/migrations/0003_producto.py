from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0002_update_cita_estado"),
    ]

    operations = [
        migrations.CreateModel(
            name="Producto",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=150)),
                ("descripcion", models.TextField()),
                (
                    "categoria",
                    models.CharField(
                        choices=[
                            ("alimentos", "Alimentos"),
                            ("medicamentos", "Medicamentos"),
                            ("accesorios", "Accesorios"),
                        ],
                        max_length=30,
                    ),
                ),
                (
                    "precio",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=8,
                        validators=[MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("imagen", models.ImageField(blank=True, null=True, upload_to="productos/")),
                ("disponible", models.BooleanField(default=True)),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("actualizado", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-actualizado"]},
        ),
    ]

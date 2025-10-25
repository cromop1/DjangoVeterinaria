from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0003_producto"),
    ]

    operations = [
        migrations.CreateModel(
            name="VacunaRecomendada",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=150)),
                (
                    "especie",
                    models.CharField(
                        choices=[("canino", "Canino"), ("felino", "Felino")],
                        max_length=20,
                    ),
                ),
                ("descripcion", models.TextField(blank=True)),
                ("edad_recomendada", models.PositiveIntegerField()),
                (
                    "unidad_tiempo",
                    models.CharField(
                        choices=[("semanas", "Semanas"), ("meses", "Meses"), ("anios", "Años")],
                        max_length=10,
                    ),
                ),
                ("refuerzo", models.CharField(blank=True, max_length=150)),
                ("orden", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ["especie", "orden", "nombre"]},
        ),
        migrations.CreateModel(
            name="VacunaRegistro",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha_aplicacion", models.DateField()),
                ("notas", models.TextField(blank=True)),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("actualizado", models.DateTimeField(auto_now=True)),
                (
                    "paciente",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="registros_vacunas",
                        to="Core.paciente",
                    ),
                ),
                (
                    "vacuna",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="registros",
                        to="Core.vacunarecomendada",
                    ),
                ),
            ],
            options={"ordering": ["-fecha_aplicacion", "-actualizado"]},
        ),
        migrations.AlterUniqueTogether(
            name="vacunarecomendada",
            unique_together={("especie", "nombre")},
        ),
        migrations.AlterUniqueTogether(
            name="vacunaregistro",
            unique_together={("paciente", "vacuna")},
        ),
    ]

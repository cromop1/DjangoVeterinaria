import django.db.models.deletion
from django.db import migrations, models


def copiar_relaciones_existentes(apps, schema_editor):
    CitaFarmaco = apps.get_model("Core", "CitaFarmaco")

    tabla_antigua = "Core_cita_farmacos_utilizados"
    with schema_editor.connection.cursor() as cursor:
        try:
            cursor.execute(f"SELECT cita_id, farmaco_id FROM {tabla_antigua}")
        except Exception:
            return
        filas = cursor.fetchall()

    registros = []
    combinaciones = set()
    for cita_id, farmaco_id in filas:
        clave = (cita_id, farmaco_id)
        if clave in combinaciones:
            continue
        combinaciones.add(clave)
        registros.append(
            CitaFarmaco(cita_id=cita_id, farmaco_id=farmaco_id, cantidad=1)
        )

    if registros:
        CitaFarmaco.objects.bulk_create(registros, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0013_cita_farmacos_utilizados"),
    ]

    operations = [
        migrations.CreateModel(
            name="CitaFarmaco",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("cantidad", models.PositiveIntegerField(default=1)),
                ("registrado", models.DateTimeField(auto_now_add=True)),
                (
                    "cita",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="administraciones_farmacos",
                        to="Core.cita",
                    ),
                ),
                (
                    "farmaco",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="administraciones",
                        to="Core.farmaco",
                    ),
                ),
            ],
            options={
                "ordering": ["farmaco__nombre"],
                "unique_together": {("cita", "farmaco")},
            },
        ),
        migrations.AlterField(
            model_name="cita",
            name="farmacos_utilizados",
            field=models.ManyToManyField(
                blank=True,
                help_text="Medicamentos del inventario utilizados durante la atención.",
                related_name="citas_utilizadas",
                through="Core.CitaFarmaco",
                through_fields=("cita", "farmaco"),
                to="Core.farmaco",
            ),
        ),
        migrations.RunPython(copiar_relaciones_existentes, migrations.RunPython.noop),
    ]

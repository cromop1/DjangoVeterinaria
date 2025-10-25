import django.db.models.deletion
from django.db import migrations, models


def create_default_branch(apps, schema_editor):
    Sucursal = apps.get_model("Core", "Sucursal")
    User = apps.get_model("Core", "User")
    Cita = apps.get_model("Core", "Cita")

    sucursal, _created = Sucursal.objects.get_or_create(
        nombre="Casa Central",
        defaults={"direccion": "Actualizar dirección de la sucursal"},
    )

    User.objects.filter(
        rol__in=["ADMIN", "ADMIN_OP", "VET"],
        sucursal__isnull=True,
    ).update(sucursal=sucursal)

    Cita.objects.filter(sucursal__isnull=True).update(sucursal=sucursal)


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0009_historialmedico_sin_proximo_control"),
    ]

    operations = [
        migrations.CreateModel(
            name="Sucursal",
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
                ("nombre", models.CharField(max_length=150, unique=True)),
                ("direccion", models.CharField(max_length=255)),
                ("ciudad", models.CharField(blank=True, max_length=120)),
                ("telefono", models.CharField(blank=True, max_length=30)),
            ],
            options={"ordering": ["nombre"]},
        ),
        migrations.AddField(
            model_name="user",
            name="sucursal",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="usuarios",
                to="Core.sucursal",
            ),
        ),
        migrations.AddField(
            model_name="cita",
            name="sucursal",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="citas",
                to="Core.sucursal",
            ),
        ),
        migrations.RunPython(create_default_branch, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="cita",
            name="sucursal",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="citas",
                to="Core.sucursal",
            ),
        ),
    ]

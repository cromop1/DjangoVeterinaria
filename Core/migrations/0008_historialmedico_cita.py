from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0007_producto_telefono_contacto"),
    ]

    operations = [
        migrations.AddField(
            model_name="historialmedico",
            name="cita",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="historial_medico",
                to="Core.cita",
            ),
        ),
    ]

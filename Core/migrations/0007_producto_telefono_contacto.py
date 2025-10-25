from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0006_cita_fecha_solicitada"),
    ]

    operations = [
        migrations.AddField(
            model_name="producto",
            name="telefono_contacto",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]

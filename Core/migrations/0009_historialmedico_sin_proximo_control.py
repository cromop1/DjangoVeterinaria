from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0008_historialmedico_cita"),
    ]

    operations = [
        migrations.AddField(
            model_name="historialmedico",
            name="sin_proximo_control",
            field=models.BooleanField(default=False),
        ),
    ]

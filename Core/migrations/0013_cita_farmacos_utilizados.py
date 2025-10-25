from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0012_farmaco"),
    ]

    operations = [
        migrations.AddField(
            model_name="cita",
            name="farmacos_utilizados",
            field=models.ManyToManyField(
                blank=True,
                help_text="Medicamentos del inventario utilizados durante la atención.",
                related_name="citas_utilizadas",
                to="Core.farmaco",
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Core", "0010_sucursal"),
    ]

    operations = [
        migrations.AddField(
            model_name="sucursal",
            name="imagen",
            field=models.ImageField(blank=True, null=True, upload_to="sucursales/"),
        ),
    ]

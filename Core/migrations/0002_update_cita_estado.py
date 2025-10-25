from django.db import migrations, models


def set_pending_status(apps, schema_editor):
    Cita = apps.get_model('Core', 'Cita')
    Cita.objects.filter(estado='programada', veterinario__isnull=True).update(estado='pendiente')


class Migration(migrations.Migration):

    dependencies = [
        ('Core', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cita',
            name='estado',
            field=models.CharField(
                choices=[
                    ('pendiente', 'Pendiente'),
                    ('programada', 'Programada'),
                    ('atendida', 'Atendida'),
                    ('cancelada', 'Cancelada'),
                ],
                default='pendiente',
                max_length=20,
            ),
        ),
        migrations.RunPython(set_pending_status, migrations.RunPython.noop),
    ]

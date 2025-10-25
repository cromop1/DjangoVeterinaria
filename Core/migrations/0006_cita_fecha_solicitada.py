from django.db import migrations, models
from django.utils import timezone


def establecer_fecha_solicitada(apps, schema_editor):
    Cita = apps.get_model('Core', 'Cita')
    for cita in Cita.objects.all():
        if cita.fecha_hora:
            cita.fecha_solicitada = cita.fecha_hora.date()
        else:
            cita.fecha_solicitada = timezone.localdate()
        cita.save(update_fields=['fecha_solicitada'])


def revertir_fecha_solicitada(apps, schema_editor):
    Cita = apps.get_model('Core', 'Cita')
    for cita in Cita.objects.all():
        cita.fecha_solicitada = timezone.localdate()
        cita.save(update_fields=['fecha_solicitada'])


class Migration(migrations.Migration):

    dependencies = [
        ('Core', '0005_seed_vacunas'),
    ]

    operations = [
        migrations.AddField(
            model_name='cita',
            name='fecha_solicitada',
            field=models.DateField(default=timezone.now),
        ),
        migrations.AlterField(
            model_name='cita',
            name='fecha_hora',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(establecer_fecha_solicitada, revertir_fecha_solicitada),
    ]

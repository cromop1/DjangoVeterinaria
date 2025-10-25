from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver


User = get_user_model()


@receiver(post_save, sender=User)
def bootstrap_related_profiles(sender, instance, created, **kwargs):
    """Ensure auxiliary data stays in sync when nuevos usuarios se crean."""

    if created and instance.rol == "VET" and not instance.activo:
        # Al crear veterinarios desde el admin la casilla "activo" aparecía
        # desmarcada, lo que impedía asignarlos. Forzamos el valor por defecto
        # para que queden disponibles inmediatamente.
        instance.activo = True
        instance.save(update_fields=["activo"])

    if instance.rol == "OWNER":
        Propietario = apps.get_model("Core", "Propietario")
        Propietario.objects.get_or_create(
            user=instance,
            defaults={
                "telefono": instance.telefono,
                "direccion": instance.direccion,
            },
        )

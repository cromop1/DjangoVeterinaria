from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Core'

    def ready(self):
        # Importar señales para que se registren al iniciar la app.
        from . import signals  # noqa: F401

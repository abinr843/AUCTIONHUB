from django.apps import AppConfig
import threading
class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from .scheduler import run_scheduler  # Moved here to prevent AppRegistryNotReady
        threading.Thread(target=run_scheduler, daemon=True).start()

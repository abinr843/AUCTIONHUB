from django.apps import AppConfig
import threading
from .scheduler import run_scheduler  # Import your scheduler function

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        threading.Thread(target=run_scheduler, daemon=True).start()

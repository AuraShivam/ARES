from django.apps import AppConfig


class SupplyChainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "supply_chain"

    def ready(self):
        from . import realtime_signals  # noqa: F401

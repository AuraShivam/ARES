import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_delete, post_save


logger = logging.getLogger("ares.realtime")
GROUP_NAME = "ares.dashboard.events"
IGNORED_MODELS = {"dataimportrow"}


def _publish_change(resource, action):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(GROUP_NAME, {
            "type": "dashboard.data_changed",
            "resource": resource,
            "action": action,
        })
    except Exception as exc:
        logger.warning("Dashboard event could not be published", extra={"error_type": type(exc).__name__})


def _on_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    action = "created" if created else "updated"
    transaction.on_commit(
        lambda: _publish_change(sender._meta.model_name, action),
        robust=True,
    )


def _on_delete(sender, instance, **kwargs):
    transaction.on_commit(
        lambda: _publish_change(sender._meta.model_name, "deleted"),
        robust=True,
    )


def connect_model_signals():
    for model in apps.get_app_config("supply_chain").get_models():
        if model._meta.model_name in IGNORED_MODELS:
            continue
        signal_id = model._meta.label_lower
        post_save.connect(_on_save, sender=model, dispatch_uid=f"ares.realtime.save.{signal_id}")
        post_delete.connect(_on_delete, sender=model, dispatch_uid=f"ares.realtime.delete.{signal_id}")


connect_model_signals()

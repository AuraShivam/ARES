import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_delete, post_save


logger = logging.getLogger("ares.realtime")
GROUP_NAME = "ares.dashboard.events"
IGNORED_MODELS = {"dataimportrow", "digitaltwinchangeevent", "digitaltwinsimulation"}
TWIN_TRACKED_MODELS = {
    "supplier", "warehouse", "material", "inventory", "inventorymovement",
    "purchaseorder", "purchaseorderline", "shipment", "disruption",
    "responseplan", "responseaction", "responseactionexecution",
    "externalfeed", "externalfeedevent",
}


def _publish_change(resource, action, sequence=None, entity_id=""):
    event_record = None
    try:
        if sequence is not None:
            model = apps.get_model("supply_chain", "DigitalTwinChangeEvent")
            event_record = model.objects.filter(sequence=sequence).first()
            if event_record is None or event_record.published_at is not None:
                return
            event_record.delivery_attempts += 1
            event_record.last_delivery_error = ""
            event_record.save(update_fields=["delivery_attempts", "last_delivery_error"])
        channel_layer = get_channel_layer()
        if channel_layer is None:
            if event_record:
                event_record.last_delivery_error = "channel_layer_unavailable"
                event_record.save(update_fields=["last_delivery_error"])
            return
        async_to_sync(channel_layer.group_send)(GROUP_NAME, {
            "type": "dashboard.data_changed",
            "resource": resource,
            "action": action,
            "sequence": sequence,
            "entity_id": entity_id,
        })
        if event_record:
            from django.utils import timezone
            event_record.published_at = timezone.now()
            event_record.save(update_fields=["published_at"])
    except Exception as exc:
        if event_record:
            try:
                event_record.last_delivery_error = type(exc).__name__[:120]
                event_record.save(update_fields=["last_delivery_error"])
            except Exception:
                logger.warning("Dashboard event retry state could not be saved", extra={"error_type": type(exc).__name__})
        logger.warning("Dashboard event could not be published", extra={"error_type": type(exc).__name__})


def _on_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    action = "created" if created else "updated"
    _schedule_change(sender, instance, action)


def _on_delete(sender, instance, **kwargs):
    _schedule_change(sender, instance, "deleted")


def _schedule_change(sender, instance, action):
    resource = sender._meta.model_name
    if resource in TWIN_TRACKED_MODELS:
        model = apps.get_model("supply_chain", "DigitalTwinChangeEvent")
        event = model.objects.create(resource=resource, entity_id=str(instance.pk), action=action)
        transaction.on_commit(
            lambda sequence=event.sequence, value=resource, change=action, entity_id=str(instance.pk):
                _publish_change(value, change, sequence=sequence, entity_id=entity_id),
            robust=True,
        )
    else:
        transaction.on_commit(lambda: _publish_change(resource, action), robust=True)


def connect_model_signals():
    for model in apps.get_app_config("supply_chain").get_models():
        if model._meta.model_name in IGNORED_MODELS:
            continue
        signal_id = model._meta.label_lower
        post_save.connect(_on_save, sender=model, dispatch_uid=f"ares.realtime.save.{signal_id}")
        post_delete.connect(_on_delete, sender=model, dispatch_uid=f"ares.realtime.delete.{signal_id}")


connect_model_signals()

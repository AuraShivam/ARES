import json
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import (
    AuditEvent, Disruption, Inventory, InventoryMovement, Material, PurchaseOrder,
    PurchaseOrderLine, Shipment, Supplier, Warehouse,
)
from .risk import assess
from .serializers import (
    AuditEventSerializer, DisruptionSerializer, InventoryMovementSerializer,
    InventorySerializer, MaterialSerializer, PurchaseOrderLineSerializer,
    PurchaseOrderSerializer, ShipmentSerializer, SupplierSerializer, WarehouseSerializer,
)


class AuditMixin:
    def _audit_actor(self):
        user = getattr(self.request, "user", None)
        return user.get_username() if user and user.is_authenticated else "local-demo"

    def _audit(self, instance, action, before=None, after=None):
        AuditEvent.objects.create(
            entity_type=instance._meta.label_lower,
            entity_id=str(instance.pk),
            action=action,
            actor=self._audit_actor(),
            changes={"before": before, "after": after},
        )

    def _snapshot(self, instance):
        return json.loads(json.dumps(dict(self.get_serializer(instance).data), cls=DjangoJSONEncoder))

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        self._audit(instance, "create", after=self._snapshot(instance))

    @transaction.atomic
    def perform_update(self, serializer):
        before = self._snapshot(serializer.instance)
        instance = serializer.save()
        self._audit(instance, "update", before=before, after=self._snapshot(instance))

    @transaction.atomic
    def perform_destroy(self, instance):
        before = self._snapshot(instance)
        entity_type, entity_id = instance._meta.label_lower, str(instance.pk)
        instance.delete()
        AuditEvent.objects.create(
            entity_type=entity_type, entity_id=entity_id, action="delete",
            actor=self._audit_actor(), changes={"before": before, "after": None},
        )


class AuditedModelViewSet(AuditMixin, viewsets.ModelViewSet):
    pass


class SupplierViewSet(AuditedModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer


class MaterialViewSet(AuditedModelViewSet):
    queryset = Material.objects.select_related("preferred_supplier").all()
    serializer_class = MaterialSerializer


class WarehouseViewSet(AuditedModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer


class InventoryViewSet(AuditedModelViewSet):
    queryset = Inventory.objects.select_related("material", "warehouse").all()
    serializer_class = InventorySerializer


class PurchaseOrderViewSet(AuditedModelViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier", "material").prefetch_related("lines__material").all()
    serializer_class = PurchaseOrderSerializer


class PurchaseOrderLineViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PurchaseOrderLine.objects.select_related("purchase_order", "material").all()
    serializer_class = PurchaseOrderLineSerializer


class InventoryMovementViewSet(AuditMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                               mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = InventoryMovement.objects.select_related("inventory__material", "inventory__warehouse").all()
    serializer_class = InventoryMovementSerializer


class ShipmentViewSet(AuditedModelViewSet):
    queryset = Shipment.objects.select_related("purchase_order").all()
    serializer_class = ShipmentSerializer


class DisruptionViewSet(AuditedModelViewSet):
    queryset = Disruption.objects.select_related("affected_supplier", "affected_shipment").all()
    serializer_class = DisruptionSerializer


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditEvent.objects.all()
    serializer_class = AuditEventSerializer


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "ARES API", "database": "configured local SQLite"})


@api_view(["GET"])
def overview(request):
    return Response({
        "suppliers": Supplier.objects.count(), "materials": Material.objects.count(),
        "warehouses": Warehouse.objects.count(), "inventory_records": Inventory.objects.count(),
        "low_inventory": Inventory.objects.filter(quantity__lte=F("reorder_point")).count(),
        "purchase_orders": PurchaseOrder.objects.count(), "purchase_order_lines": PurchaseOrderLine.objects.count(),
        "inventory_movements": InventoryMovement.objects.count(),
        "open_disruptions": Disruption.objects.exclude(status="resolved").count(),
        "at_risk_shipments": Shipment.objects.filter(status__in=["delayed", "at_risk"]).count(),
    })


@api_view(["POST"])
def risk_assess(request):
    disruption_id = request.data.get("disruption_id")
    if disruption_id:
        try:
            disruption = Disruption.objects.select_related("affected_supplier", "affected_shipment").get(pk=disruption_id)
        except (Disruption.DoesNotExist, ValueError, ValidationError):
            return Response({"detail": "Disruption not found."}, status=status.HTTP_404_NOT_FOUND)
    else:
        serializer = DisruptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        disruption = serializer.save()
        disruption = Disruption.objects.select_related("affected_supplier", "affected_shipment").get(pk=disruption.pk)
    return Response(assess(disruption))

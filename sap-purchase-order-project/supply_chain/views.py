from django.core.exceptions import ValidationError
from django.db.models import F
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Disruption, Inventory, Material, PurchaseOrder, Shipment, Supplier
from .risk import assess
from .serializers import (DisruptionSerializer, InventorySerializer, MaterialSerializer,
                          PurchaseOrderSerializer, ShipmentSerializer, SupplierSerializer)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer


class MaterialViewSet(viewsets.ModelViewSet):
    queryset = Material.objects.select_related("preferred_supplier").all()
    serializer_class = MaterialSerializer


class InventoryViewSet(viewsets.ModelViewSet):
    queryset = Inventory.objects.select_related("material").all()
    serializer_class = InventorySerializer


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier", "material").all()
    serializer_class = PurchaseOrderSerializer


class ShipmentViewSet(viewsets.ModelViewSet):
    queryset = Shipment.objects.select_related("purchase_order").all()
    serializer_class = ShipmentSerializer


class DisruptionViewSet(viewsets.ModelViewSet):
    queryset = Disruption.objects.select_related("affected_supplier", "affected_shipment").all()
    serializer_class = DisruptionSerializer


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "ARES API", "database": "configured local SQLite"})


@api_view(["GET"])
def overview(request):
    return Response({
        "suppliers": Supplier.objects.count(), "materials": Material.objects.count(),
        "inventory_records": Inventory.objects.count(), "low_inventory": Inventory.objects.filter(quantity__lte=F("reorder_point")).count(),
        "purchase_orders": PurchaseOrder.objects.count(), "open_disruptions": Disruption.objects.exclude(status="resolved").count(),
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

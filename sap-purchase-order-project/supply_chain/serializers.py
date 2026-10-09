from rest_framework import serializers
from .models import Disruption, Inventory, Material, PurchaseOrder, Shipment, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = "__all__"


class MaterialSerializer(serializers.ModelSerializer):
    preferred_supplier_name = serializers.CharField(source="preferred_supplier.name", read_only=True, default=None)

    class Meta:
        model = Material
        fields = "__all__"


class InventorySerializer(serializers.ModelSerializer):
    material_sku = serializers.CharField(source="material.sku", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    below_reorder_point = serializers.BooleanField(read_only=True)

    class Meta:
        model = Inventory
        fields = "__all__"


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    material_sku = serializers.CharField(source="material.sku", read_only=True)
    total_value = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = "__all__"

    def get_total_value(self, obj):
        return str(obj.quantity * obj.unit_price)


class ShipmentSerializer(serializers.ModelSerializer):
    purchase_order_number = serializers.CharField(source="purchase_order.number", read_only=True)

    class Meta:
        model = Shipment
        fields = "__all__"


class DisruptionSerializer(serializers.ModelSerializer):
    affected_supplier_name = serializers.CharField(source="affected_supplier.name", read_only=True, default=None)
    affected_shipment_reference = serializers.CharField(source="affected_shipment.reference", read_only=True, default=None)

    class Meta:
        model = Disruption
        fields = "__all__"

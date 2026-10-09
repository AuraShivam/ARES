from decimal import Decimal
from hashlib import sha1

from django.db import transaction
from rest_framework import serializers

from .models import (
    AuditEvent, Disruption, Inventory, InventoryMovement, Material, PurchaseOrder,
    PurchaseOrderLine, Shipment, Supplier, Warehouse,
)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = "__all__"


class MaterialSerializer(serializers.ModelSerializer):
    preferred_supplier_name = serializers.CharField(source="preferred_supplier.name", read_only=True, default=None)

    class Meta:
        model = Material
        fields = "__all__"


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = "__all__"


def _warehouse_code_for_label(location):
    clean_name = location.strip()
    return f"LOC-{sha1(clean_name.casefold().encode('utf-8')).hexdigest()[:12].upper()}"


def _warehouse_for_label(location):
    clean_name = location.strip()
    code = _warehouse_code_for_label(clean_name)
    warehouse, _ = Warehouse.objects.get_or_create(code=code, defaults={"name": clean_name})
    return warehouse


class InventorySerializer(serializers.ModelSerializer):
    material_sku = serializers.CharField(source="material.sku", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True, default=None)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True, default=None)
    below_reorder_point = serializers.BooleanField(read_only=True)
    location = serializers.CharField(required=False, allow_blank=True)
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Inventory
        fields = "__all__"

    def validate(self, attrs):
        warehouse = attrs.get("warehouse", getattr(self.instance, "warehouse", None))
        location = attrs.get("location", getattr(self.instance, "location", ""))
        if "location" in attrs:
            location = location.strip()
            attrs["location"] = location
            if self.instance and "warehouse" not in attrs and location == self.instance.location:
                warehouse = self.instance.warehouse
            elif "warehouse" not in attrs:
                warehouse = Warehouse.objects.filter(code=_warehouse_code_for_label(location)).first() if location else None
        material = attrs.get("material", getattr(self.instance, "material", None))
        if not warehouse and not location:
            raise serializers.ValidationError({"warehouse": "Choose a warehouse or provide a legacy location label."})
        if warehouse and not warehouse.active and (self.instance is None or warehouse.pk != self.instance.warehouse_id):
            raise serializers.ValidationError({"warehouse": "Inactive warehouses cannot receive new inventory balances."})
        effective_location = location or (warehouse.name if warehouse else "")
        if "warehouse" in attrs and warehouse and "location" not in attrs:
            effective_location = warehouse.name
        if material and effective_location:
            duplicate_location = Inventory.objects.filter(material=material, location=effective_location)
            if self.instance:
                duplicate_location = duplicate_location.exclude(pk=self.instance.pk)
            if duplicate_location.exists():
                raise serializers.ValidationError({"location": "This material already has a balance at that location."})
        if material and warehouse:
            duplicate = Inventory.objects.filter(material=material, warehouse=warehouse)
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError({"warehouse": "This material already has a balance at that warehouse."})
        return attrs

    def _resolve_warehouse(self, validated_data):
        warehouse = validated_data.get("warehouse")
        location = validated_data.get("location", "")
        if warehouse is None and location:
            warehouse = _warehouse_for_label(location)
            validated_data["warehouse"] = warehouse
        if warehouse and not location:
            validated_data["location"] = warehouse.name
        return validated_data

    def create(self, validated_data):
        return super().create(self._resolve_warehouse(validated_data))

    def update(self, instance, validated_data):
        return super().update(instance, self._resolve_warehouse(validated_data))


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    line_number = serializers.IntegerField(required=False, min_value=1, max_value=32767)
    material_sku = serializers.CharField(source="material.sku", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLine
        fields = "__all__"
        read_only_fields = ("purchase_order", "created_at", "updated_at")

    def get_line_total(self, obj):
        return str(obj.line_total)

    def validate(self, attrs):
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", None))
        received = attrs.get("received_quantity", getattr(self.instance, "received_quantity", Decimal("0")))
        if quantity is not None and received > quantity:
            raise serializers.ValidationError({"received_quantity": "Received quantity cannot exceed the ordered quantity."})
        return attrs


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    material_sku = serializers.CharField(source="material.sku", read_only=True)
    lines = PurchaseOrderLineSerializer(many=True, required=False)
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all(), required=False)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, min_value=Decimal("0.01"))
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, min_value=Decimal("0"))
    total_value = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = "__all__"

    def validate(self, attrs):
        lines = attrs.get("lines")
        if self.instance is None and lines is None:
            missing = [field for field in ("material", "quantity") if field not in attrs]
            if missing:
                raise serializers.ValidationError({field: "Required for the legacy single-line PO format or provide lines." for field in missing})
        if lines is not None:
            if not lines:
                raise serializers.ValidationError({"lines": "A purchase order must contain at least one line."})
            for index, line in enumerate(lines, start=1):
                line.setdefault("line_number", index)
            line_numbers = [line["line_number"] for line in lines if line.get("line_number") is not None]
            if len(line_numbers) != len(set(line_numbers)):
                raise serializers.ValidationError({"lines": "Line numbers must be unique within a purchase order."})
        elif self.instance:
            first = self.instance.lines.order_by("line_number").first()
            new_quantity = attrs.get("quantity", self.instance.quantity)
            if first and first.received_quantity > new_quantity:
                raise serializers.ValidationError({"quantity": "Quantity cannot be lower than the received quantity on the first line."})
        return attrs

    def get_total_value(self, obj):
        if obj.lines.exists():
            return str(sum((line.line_total for line in obj.lines.all()), Decimal("0")))
        return str((obj.quantity * obj.unit_price).quantize(Decimal("0.01")))

    @transaction.atomic
    def create(self, validated_data):
        lines_data = validated_data.pop("lines", None)
        if lines_data:
            first = lines_data[0]
            validated_data["material"] = first["material"]
            validated_data["quantity"] = first["quantity"]
            validated_data["unit_price"] = first.get("unit_price", Decimal("0"))
        purchase_order = PurchaseOrder.objects.create(**validated_data)
        if lines_data:
            for index, line in enumerate(lines_data, start=1):
                line.setdefault("line_number", index)
                PurchaseOrderLine.objects.create(purchase_order=purchase_order, **line)
        else:
            PurchaseOrderLine.objects.create(
                purchase_order=purchase_order, line_number=1, material=purchase_order.material,
                quantity=purchase_order.quantity, unit_price=purchase_order.unit_price,
            )
        return purchase_order

    @transaction.atomic
    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", serializers.empty)
        instance = super().update(instance, validated_data)
        if lines_data is not serializers.empty:
            if not lines_data:
                raise serializers.ValidationError({"lines": "A purchase order must contain at least one line."})
            existing_lines = {line.line_number: line for line in instance.lines.all()}
            included_line_numbers = set()
            for index, line in enumerate(lines_data, start=1):
                line.setdefault("line_number", index)
                line_number = line["line_number"]
                included_line_numbers.add(line_number)
                existing = existing_lines.get(line_number)
                if existing:
                    for field, value in line.items():
                        setattr(existing, field, value)
                    existing.save()
                else:
                    PurchaseOrderLine.objects.create(purchase_order=instance, **line)
            instance.lines.exclude(line_number__in=included_line_numbers).delete()
            first = lines_data[0]
            instance.material = first["material"]
            instance.quantity = first["quantity"]
            instance.unit_price = first.get("unit_price", Decimal("0"))
            instance.save(update_fields=["material", "quantity", "unit_price", "updated_at"])
        elif any(field in validated_data for field in ("material", "quantity", "unit_price")):
            first = instance.lines.order_by("line_number").first()
            if first:
                first.material = instance.material
                first.quantity = instance.quantity
                first.unit_price = instance.unit_price
                first.save(update_fields=["material", "quantity", "unit_price", "updated_at"])
        return instance


class InventoryMovementSerializer(serializers.ModelSerializer):
    material_sku = serializers.CharField(source="inventory.material.sku", read_only=True)
    warehouse_name = serializers.CharField(source="inventory.warehouse.name", read_only=True, default=None)
    resulting_quantity = serializers.DecimalField(source="balance_after", max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = InventoryMovement
        fields = "__all__"
        read_only_fields = ("actor", "balance_after", "created_at", "updated_at")

    def validate(self, attrs):
        movement_type = attrs.get("movement_type", getattr(self.instance, "movement_type", None))
        delta = attrs.get("quantity_delta", getattr(self.instance, "quantity_delta", None))
        if delta is not None and delta == 0:
            raise serializers.ValidationError({"quantity_delta": "Movement quantity must be non-zero."})
        if movement_type == "receipt" and delta is not None and delta < 0:
            raise serializers.ValidationError({"quantity_delta": "Receipts must increase inventory."})
        if movement_type == "issue" and delta is not None and delta > 0:
            raise serializers.ValidationError({"quantity_delta": "Issues must use a negative quantity delta."})
        inventory = attrs.get("inventory", getattr(self.instance, "inventory", None))
        if self.instance is None and inventory and delta is not None and inventory.quantity + delta < 0:
            raise serializers.ValidationError({"quantity_delta": "The movement would make on-hand inventory negative."})
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["actor"] = request.user.get_username() if request and request.user.is_authenticated else "anonymous"
        with transaction.atomic():
            inventory = Inventory.objects.select_for_update().get(pk=validated_data["inventory"].pk)
            delta = validated_data["quantity_delta"]
            if inventory.quantity + delta < 0:
                raise serializers.ValidationError({"quantity_delta": "The movement would make on-hand inventory negative."})
            validated_data["balance_after"] = inventory.quantity + delta
            movement = InventoryMovement.objects.create(**validated_data)
            inventory.quantity += delta
            inventory.save(update_fields=["quantity", "updated_at"])
        return movement


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


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = "__all__"
        read_only_fields = ("id", "entity_type", "entity_id", "action", "actor", "changes", "created_at")

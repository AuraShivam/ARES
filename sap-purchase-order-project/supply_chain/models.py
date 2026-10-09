import uuid
from decimal import Decimal
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Supplier(TimestampedModel):
    name = models.CharField(max_length=180)
    code = models.CharField(max_length=40, unique=True)
    country = models.CharField(max_length=80, blank=True)
    region = models.CharField(max_length=100, blank=True)
    risk_score = models.PositiveSmallIntegerField(default=20, validators=[MaxValueValidator(100)])
    lead_time_days = models.PositiveSmallIntegerField(default=14)
    status = models.CharField(max_length=20, choices=[("active", "Active"), ("watch", "Watch"), ("blocked", "Blocked")], default="active")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Material(TimestampedModel):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=20, default="EA")
    criticality = models.CharField(max_length=20, choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")], default="medium")
    preferred_supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="materials")

    class Meta:
        ordering = ["sku"]

    def __str__(self):
        return f"{self.sku} — {self.name}"


class Warehouse(TimestampedModel):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    region = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=80, blank=True)
    warehouse_type = models.CharField(max_length=20, choices=[("distribution", "Distribution center"), ("factory", "Factory"), ("supplier", "Supplier site"), ("other", "Other")], default="distribution")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Inventory(TimestampedModel):
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="inventory")
    # `location` remains as a compatibility label for existing API clients.
    location = models.CharField(max_length=120)
    warehouse = models.ForeignKey(Warehouse, null=True, blank=True, on_delete=models.PROTECT, related_name="inventory")
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reorder_point = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["material__sku", "location"]
        constraints = [
            models.UniqueConstraint(fields=["material", "location"], name="unique_material_location_inventory"),
            models.UniqueConstraint(fields=["material", "warehouse"], condition=Q(warehouse__isnull=False), name="unique_material_warehouse_inventory"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="inventory_quantity_nonnegative"),
            models.CheckConstraint(condition=Q(reorder_point__gte=0), name="inventory_reorder_nonnegative"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="inventory_cost_nonnegative"),
        ]

    @property
    def below_reorder_point(self):
        return self.quantity <= self.reorder_point


class InventoryMovement(TimestampedModel):
    TYPES = [("receipt", "Receipt"), ("issue", "Issue"), ("adjustment", "Adjustment")]
    inventory = models.ForeignKey(Inventory, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=TYPES)
    # Receipts use positive deltas; issues use negative deltas; adjustments may be either.
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reference = models.CharField(max_length=80, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    actor = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(quantity_delta=0), name="inventory_movement_nonzero_delta"),
            models.CheckConstraint(
                condition=(
                    Q(movement_type="receipt", quantity_delta__gt=0)
                    | Q(movement_type="issue", quantity_delta__lt=0)
                    | Q(movement_type="adjustment", quantity_delta__gt=0)
                    | Q(movement_type="adjustment", quantity_delta__lt=0)
                ),
                name="inventory_movement_direction_valid",
            ),
        ]


class PurchaseOrder(TimestampedModel):
    STATUS = [("draft", "Draft"), ("approved", "Approved"), ("in_transit", "In transit"), ("received", "Received"), ("delayed", "Delayed"), ("cancelled", "Cancelled")]
    number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="purchase_orders")
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")
    currency = models.CharField(max_length=3, default="USD")
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="purchase_order_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="purchase_order_price_nonnegative"),
        ]


class PurchaseOrderLine(TimestampedModel):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    line_number = models.PositiveSmallIntegerField()
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="purchase_order_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    received_quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["purchase_order", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["purchase_order", "line_number"], name="unique_purchase_order_line_number"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="purchase_order_line_quantity_positive"),
            models.CheckConstraint(condition=Q(received_quantity__gte=0), name="purchase_order_line_received_nonnegative"),
            models.CheckConstraint(condition=Q(received_quantity__lte=models.F("quantity")), name="purchase_order_line_received_lte_ordered"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="purchase_order_line_price_nonnegative"),
        ]

    @property
    def line_total(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


class Shipment(TimestampedModel):
    STATUS = [("planned", "Planned"), ("in_transit", "In transit"), ("delayed", "Delayed"), ("delivered", "Delivered"), ("at_risk", "At risk")]
    reference = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="shipments")
    origin = models.CharField(max_length=120)
    destination = models.CharField(max_length=120)
    carrier = models.CharField(max_length=120, blank=True)
    eta = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="planned")
    risk_score = models.PositiveSmallIntegerField(default=10, validators=[MaxValueValidator(100)])

    class Meta:
        ordering = ["eta", "reference"]


class Disruption(TimestampedModel):
    SEVERITY = [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")]
    STATUS = [("open", "Open"), ("review", "Under review"), ("mitigating", "Mitigating"), ("resolved", "Resolved")]
    title = models.CharField(max_length=180)
    disruption_type = models.CharField(max_length=80, default="logistics")
    description = models.TextField(blank=True)
    affected_region = models.CharField(max_length=120, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY, default="medium")
    status = models.CharField(max_length=20, choices=STATUS, default="open")
    confidence = models.PositiveSmallIntegerField(default=70, validators=[MaxValueValidator(100)])
    affected_supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="disruptions")
    affected_shipment = models.ForeignKey(Shipment, null=True, blank=True, on_delete=models.SET_NULL, related_name="disruptions")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80)
    action = models.CharField(max_length=20, choices=[("create", "Create"), ("update", "Update"), ("delete", "Delete")])
    actor = models.CharField(max_length=120, default="anonymous")
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

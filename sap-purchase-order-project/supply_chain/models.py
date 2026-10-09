import uuid
from django.db import models
from django.core.validators import MaxValueValidator


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


class Inventory(TimestampedModel):
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="inventory")
    location = models.CharField(max_length=120)
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reorder_point = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["material__sku", "location"]
        constraints = [models.UniqueConstraint(fields=["material", "location"], name="unique_material_location_inventory")]

    @property
    def below_reorder_point(self):
        return self.quantity <= self.reorder_point


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

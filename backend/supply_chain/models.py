import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q
from django.utils import timezone
from .geospatial import validate_route_geometry


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SourceTrackedModel(TimestampedModel):
    source_name = models.CharField(max_length=120, blank=True)
    source_key = models.CharField(max_length=160, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class Supplier(SourceTrackedModel):
    name = models.CharField(max_length=180)
    code = models.CharField(max_length=40, unique=True)
    country = models.CharField(max_length=80, blank=True)
    region = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    risk_score = models.PositiveSmallIntegerField(default=20, validators=[MaxValueValidator(100)])
    lead_time_days = models.PositiveSmallIntegerField(default=14)
    status = models.CharField(max_length=20, choices=[("active", "Active"), ("watch", "Watch"), ("blocked", "Blocked")], default="active")

    class Meta:
        ordering = ["name"]
        constraints = [models.CheckConstraint(
            condition=(Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False)),
            name="supplier_coordinate_pair",
        )]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Material(SourceTrackedModel):
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


class Warehouse(SourceTrackedModel):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    region = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=80, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    warehouse_type = models.CharField(max_length=20, choices=[("distribution", "Distribution center"), ("factory", "Factory"), ("supplier", "Supplier site"), ("other", "Other")], default="distribution")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.CheckConstraint(
            condition=(Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False)),
            name="warehouse_coordinate_pair",
        )]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Inventory(SourceTrackedModel):
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


class InventoryMovement(SourceTrackedModel):
    TYPES = [("receipt", "Receipt"), ("issue", "Issue"), ("adjustment", "Adjustment")]
    inventory = models.ForeignKey(Inventory, on_delete=models.PROTECT, related_name="movements")
    purchase_order = models.ForeignKey(
        "PurchaseOrder", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="inventory_movements",
    )
    movement_type = models.CharField(max_length=20, choices=TYPES)
    # Receipts use positive deltas; issues use negative deltas; adjustments may be either.
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, default=None)
    # Business event date is separate from created_at so imported history keeps its original date.
    occurred_at = models.DateField(default=timezone.localdate, db_index=True)
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
            models.UniqueConstraint(
                fields=["source_name", "source_key"],
                condition=~Q(source_name="") & ~Q(source_key=""),
                name="unique_inventory_movement_source_key",
            ),
        ]


class PurchaseOrder(SourceTrackedModel):
    STATUS = [("draft", "Draft"), ("approved", "Approved"), ("in_transit", "In transit"), ("received", "Received"), ("delayed", "Delayed"), ("cancelled", "Cancelled")]
    number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="purchase_orders")
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    ordered_at = models.DateField(null=True, blank=True)
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


class Shipment(SourceTrackedModel):
    STATUS = [("planned", "Planned"), ("in_transit", "In transit"), ("delayed", "Delayed"), ("delivered", "Delivered"), ("at_risk", "At risk")]
    OUTCOME_INTERVENTION = [("unknown", "Unknown"), ("none", "No intervention"),
                            ("ares_plan", "ARES response plan applied"), ("external", "External or untracked intervention")]
    reference = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="shipments")
    origin = models.CharField(max_length=120)
    destination = models.CharField(max_length=120)
    origin_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    origin_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    destination_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    destination_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    route_geometry = models.JSONField(null=True, blank=True, validators=[validate_route_geometry])
    route_geometry_source = models.CharField(max_length=120, blank=True)
    carrier = models.CharField(max_length=120, blank=True)
    eta = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)
    delivery_outcome_verified = models.BooleanField(default=False)
    delivery_outcome_verified_at = models.DateTimeField(null=True, blank=True)
    delivery_outcome_verified_by = models.CharField(max_length=150, blank=True)
    delivery_outcome_evidence = models.TextField(blank=True)
    delivery_outcome_intervention = models.CharField(max_length=12, choices=OUTCOME_INTERVENTION, default="unknown")
    delivery_outcome_response_plan = models.ForeignKey(
        "ResponsePlan", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="verified_shipments",
    )
    status = models.CharField(max_length=20, choices=STATUS, default="planned")
    risk_score = models.PositiveSmallIntegerField(default=10, validators=[MaxValueValidator(100)])

    class Meta:
        ordering = ["eta", "reference"]
        indexes = [
            models.Index(
                fields=["delivery_outcome_verified", "status", "eta"],
                name="verified_delivery_risk_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(origin_latitude__isnull=True, origin_longitude__isnull=True)
                    | Q(origin_latitude__isnull=False, origin_longitude__isnull=False)
                ),
                name="shipment_origin_coord_pair",
            ),
            models.CheckConstraint(
                condition=(
                    Q(destination_latitude__isnull=True, destination_longitude__isnull=True)
                    | Q(destination_latitude__isnull=False, destination_longitude__isnull=False)
                ),
                name="shipment_destination_coord_pair",
            ),
        ]


class Disruption(SourceTrackedModel):
    SEVERITY = [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")]
    STATUS = [("open", "Open"), ("review", "Under review"), ("mitigating", "Mitigating"), ("resolved", "Resolved")]
    title = models.CharField(max_length=180)
    disruption_type = models.CharField(max_length=80, default="logistics")
    description = models.TextField(blank=True)
    affected_region = models.CharField(max_length=120, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    severity = models.CharField(max_length=20, choices=SEVERITY, default="medium")
    status = models.CharField(max_length=20, choices=STATUS, default="open")
    confidence = models.PositiveSmallIntegerField(default=70, validators=[MaxValueValidator(100)])
    affected_supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="disruptions")
    affected_shipment = models.ForeignKey(Shipment, null=True, blank=True, on_delete=models.SET_NULL, related_name="disruptions")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False)),
                name="disruption_coordinate_pair",
            ),
            models.UniqueConstraint(
                fields=["source_name", "source_key"],
                condition=~Q(source_name="") & ~Q(source_key=""),
                name="unique_disruption_source_key",
            ),
        ]

    def __str__(self):
        return self.title


class ResponsePlan(TimestampedModel):
    STATUS = [
        ("draft", "Draft"),
        ("pending_approval", "Pending approval"),
        ("approved", "Approved"),
        ("active", "In progress"),
        ("rejected", "Rejected"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]
    disruption = models.ForeignKey(Disruption, on_delete=models.PROTECT, related_name="response_plans")
    assessment_snapshot = models.ForeignKey(
        "RiskAssessmentSnapshot", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="response_plans",
    )
    agent_execution = models.ForeignKey(
        "AgentExecution", null=True, blank=True, on_delete=models.PROTECT,
        related_name="response_plans",
    )
    source_recommendation_index = models.PositiveSmallIntegerField(null=True, blank=True)
    agent_recommendation = models.JSONField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ares_response_plans",
    )
    title = models.CharField(max_length=180)
    objective = models.TextField(blank=True)
    owner = models.CharField(max_length=120)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=STATUS, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=150, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    outcome = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["agent_execution", "source_recommendation_index"],
                name="unique_agent_handoff_selection",
            ),
            models.CheckConstraint(
                condition=(
                    Q(agent_execution__isnull=True, source_recommendation_index__isnull=True)
                    | Q(agent_execution__isnull=False, source_recommendation_index__isnull=False)
                ),
                name="response_plan_handoff_pair",
            ),
        ]

    def __str__(self):
        return self.title


class ResponseAction(TimestampedModel):
    ACTION_TYPES = [("manual", "Manual task"), ("webhook", "Configured webhook")]
    STATUS = [
        ("pending", "Pending"),
        ("in_progress", "In progress"),
        ("blocked", "Blocked"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]
    plan = models.ForeignKey(ResponsePlan, on_delete=models.CASCADE, related_name="actions")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    owner = models.CharField(max_length=120)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    outcome = models.TextField(blank=True)
    position = models.PositiveSmallIntegerField(default=1)
    action_type = models.CharField(max_length=16, choices=ACTION_TYPES, default="manual")
    execution_payload = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "position"], name="unique_response_action_position"),
        ]


class ResponseActionExecution(TimestampedModel):
    MODES = [("dry_run", "Dry run"), ("live", "Live")]
    STATUSES = [
        ("running", "Running"),
        ("simulated", "Simulated"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    action = models.ForeignKey(ResponseAction, on_delete=models.PROTECT, related_name="executions")
    idempotency_key = models.CharField(max_length=128, unique=True)
    request_hash = models.CharField(max_length=64)
    adapter = models.CharField(max_length=40)
    mode = models.CharField(max_length=12, choices=MODES)
    status = models.CharField(max_length=12, choices=STATUSES)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    requested_by = models.CharField(max_length=150)
    approved_by = models.CharField(max_length=150, blank=True)
    result_summary = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["action", "created_at"], name="action_exec_history_idx")]


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


class DataImport(TimestampedModel):
    ENTITY_TYPES = [
        ("supplier", "Suppliers"),
        ("material", "Materials"),
        ("warehouse", "Warehouses"),
        ("inventory", "Inventory balances"),
        ("purchase_order", "Purchase orders"),
        ("shipment", "Shipments"),
        ("disruption", "Disruptions"),
    ]
    DUPLICATE_POLICIES = [("skip", "Skip existing"), ("update", "Update existing"), ("error", "Fail on duplicates")]
    STATUSES = [("preview", "Preview"), ("committed", "Committed")]

    entity_type = models.CharField(max_length=30, choices=ENTITY_TYPES)
    duplicate_policy = models.CharField(max_length=12, choices=DUPLICATE_POLICIES, default="skip")
    source_name = models.CharField(max_length=120)
    file_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUSES, default="preview")
    total_rows = models.PositiveIntegerField(default=0)
    created_rows = models.PositiveIntegerField(default=0)
    updated_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class DataImportRow(models.Model):
    ACTIONS = [
        ("create", "Will create"),
        ("update", "Will update"),
        ("skip", "Will skip"),
        ("error", "Error"),
        ("created", "Created"),
        ("updated", "Updated"),
        ("skipped", "Skipped"),
    ]
    batch = models.ForeignKey(DataImport, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    natural_key = models.CharField(max_length=250, blank=True)
    action = models.CharField(max_length=12, choices=ACTIONS)
    errors = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    record_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["row_number"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "row_number"], name="unique_import_row_number"),
        ]


class ExternalFeed(TimestampedModel):
    STATUS = [
        ("syncing", "Syncing"),
        ("never", "Never synced"),
        ("ok", "Healthy"),
        ("partial", "Partial sync"),
        ("failed", "Failed"),
        ("disabled", "Not configured"),
    ]
    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=STATUS, default="never")
    configuration = models.JSONField(default=dict, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    events_seen = models.PositiveIntegerField(default=0)
    events_created = models.PositiveIntegerField(default=0)
    events_updated = models.PositiveIntegerField(default=0)
    events_unchanged = models.PositiveIntegerField(default=0)
    events_ignored = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]


class ExternalFeedEvent(TimestampedModel):
    LIFECYCLE = [
        ("active", "Active"),
        ("cancelled", "Cancelled by source"),
        ("expired", "Expired"),
    ]
    feed = models.ForeignKey(ExternalFeed, on_delete=models.CASCADE, related_name="events")
    source_key = models.CharField(max_length=500)
    event_type = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=240)
    severity = models.CharField(max_length=20, blank=True)
    affected_region = models.CharField(max_length=240, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    effective_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    lifecycle = models.CharField(max_length=16, choices=LIFECYCLE, default="active")
    geographies = models.JSONField(default=list, blank=True)
    content_hash = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    disruption = models.ForeignKey(Disruption, null=True, blank=True, on_delete=models.SET_NULL, related_name="source_events")

    class Meta:
        ordering = ["-issued_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["feed", "source_key"], name="unique_external_feed_event_key"),
        ]


class RiskAssessmentSnapshot(TimestampedModel):
    TRIGGERS = [("manual", "Manual request"), ("source_event", "Source event")]
    disruption = models.ForeignKey(Disruption, on_delete=models.CASCADE, related_name="risk_assessments")
    source_event = models.ForeignKey(
        ExternalFeedEvent, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="risk_assessments",
    )
    trigger = models.CharField(max_length=20, choices=TRIGGERS, default="manual")
    risk_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(100)])
    risk_band = models.CharField(max_length=20)
    confidence = models.PositiveSmallIntegerField(validators=[MaxValueValidator(100)])
    model_version = models.CharField(max_length=120)
    score_breakdown = models.JSONField(default=list, blank=True)
    factors = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    recommendation = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class RiskAlert(TimestampedModel):
    STATUS = [("active", "Active"), ("cleared", "Cleared")]
    disruption = models.ForeignKey(Disruption, on_delete=models.CASCADE, related_name="risk_alerts")
    latest_assessment = models.ForeignKey(
        RiskAssessmentSnapshot, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="current_alerts",
    )
    status = models.CharField(max_length=12, choices=STATUS, default="active")
    risk_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(100)])
    risk_band = models.CharField(max_length=20)
    threshold_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(100)])
    first_triggered_at = models.DateTimeField()
    last_triggered_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    notification_due = models.BooleanField(default=True)
    alert_generation_count = models.PositiveIntegerField(default=1)
    deduplicated_count = models.PositiveIntegerField(default=0)
    cooldown_suppressed_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-last_triggered_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["disruption"], condition=models.Q(status="active"),
                name="unique_active_risk_alert_per_disruption",
            ),
        ]


class RiskOutcome(TimestampedModel):
    OUTCOMES = [("impact", "Confirmed supply-chain impact"), ("no_impact", "No material impact")]
    INTERVENTION = [("unknown", "Unknown"), ("none", "No intervention"),
                    ("ares_plan", "ARES response plan applied"), ("external", "External or untracked intervention")]
    disruption = models.OneToOneField(Disruption, on_delete=models.PROTECT, related_name="risk_outcome")
    assessment_snapshot = models.ForeignKey(
        RiskAssessmentSnapshot, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_outcomes",
    )
    response_plan = models.ForeignKey(
        ResponsePlan, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_risk_outcomes",
    )
    outcome = models.CharField(max_length=12, choices=OUTCOMES)
    intervention_status = models.CharField(max_length=12, choices=INTERVENTION, default="unknown")
    reviewed_by = models.CharField(max_length=150)
    evidence_notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField()

    class Meta:
        ordering = ["-reviewed_at"]


class ResponsePlanEffectivenessReview(TimestampedModel):
    EFFECTIVENESS = [
        ("prevented_impact", "Prevented impact"),
        ("reduced_impact", "Reduced impact"),
        ("no_measurable_effect", "No measurable effect"),
        ("worsened_impact", "Impact worsened"),
        ("unknown", "Effect unknown"),
    ]
    response_plan = models.ForeignKey(ResponsePlan, on_delete=models.PROTECT, related_name="effectiveness_reviews")
    risk_outcome = models.ForeignKey(
        RiskOutcome, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="effectiveness_reviews",
    )
    effectiveness = models.CharField(max_length=24, choices=EFFECTIVENESS)
    reviewer = models.CharField(max_length=150)
    evidence_notes = models.TextField()
    action_outcomes = models.JSONField(default=list, blank=True)
    reviewed_at = models.DateTimeField()

    class Meta:
        ordering = ["-reviewed_at", "-created_at"]
        indexes = [models.Index(fields=["response_plan", "reviewed_at"], name="plan_effect_review_idx")]


class NotificationDelivery(TimestampedModel):
    STATUSES = [
        ("pending", "Pending"),
        ("sending", "Sending"),
        ("retry", "Retry scheduled"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("unroutable", "No recipient configured"),
    ]
    idempotency_key = models.CharField(max_length=64, unique=True)
    notification_type = models.CharField(max_length=80)
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=240)
    message = models.TextField()
    status = models.CharField(max_length=16, choices=STATUSES, default="pending")
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="notification_due_idx")]


class DigitalTwinChangeEvent(models.Model):
    """Durable, ordered invalidation events used to recover after a socket disconnect."""
    sequence = models.BigAutoField(primary_key=True)
    resource = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80)
    action = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    delivery_attempts = models.PositiveIntegerField(default=0)
    last_delivery_error = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["sequence"]
        indexes = [models.Index(fields=["published_at", "sequence"], name="twin_change_pending_idx")]


class DigitalTwinSimulation(TimestampedModel):
    """Persisted what-if result; it never mutates operational records."""
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ares_digital_twin_simulations",
    )
    scenario = models.JSONField(default=dict)
    result = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]


class AgentExecution(TimestampedModel):
    """Auditable metadata and validated output for one bounded AI invocation."""

    AGENT_IDS = [
        ("risk_intelligence", "Risk intelligence"),
        ("supplier_intelligence", "Supplier intelligence"),
        ("inventory_intelligence", "Inventory intelligence"),
        ("logistics_intelligence", "Logistics intelligence"),
        ("procurement_intelligence", "Procurement intelligence"),
        ("coordinator", "Coordinator"),
    ]
    STATUSES = [
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ares_agent_executions",
    )
    workflow_disruption = models.ForeignKey(
        Disruption, null=True, blank=True, on_delete=models.PROTECT,
        related_name="ares_agent_workflows",
    )
    workflow_assessment_snapshot = models.ForeignKey(
        RiskAssessmentSnapshot, null=True, blank=True, on_delete=models.PROTECT,
        related_name="ares_agent_workflows",
    )
    agent_id = models.CharField(max_length=40, choices=AGENT_IDS)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=STATUSES, default="running")
    input_references = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=40, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    tool_call_count = models.PositiveSmallIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(
            fields=["requested_by", "idempotency_key"],
            name="uniq_agent_exec_user_idem",
        )]
        indexes = [
            models.Index(fields=["requested_by", "created_at"], name="agent_exec_user_date_idx"),
            models.Index(fields=["agent_id", "status"], name="agent_exec_type_status_idx"),
            models.Index(fields=["workflow_disruption", "created_at"], name="agent_wf_disrupt_date_idx"),
        ]
        constraints += [models.CheckConstraint(
            condition=(
                Q(workflow_disruption__isnull=True, workflow_assessment_snapshot__isnull=True)
                | Q(workflow_disruption__isnull=False, workflow_assessment_snapshot__isnull=False)
            ),
            name="agent_workflow_context_pair",
        )]


class AgentExecutionStep(TimestampedModel):
    """Auditable specialist or coordinator stage within one agent execution."""

    KINDS = [("specialist", "Specialist analysis"), ("coordination", "Coordinator synthesis")]
    STATUSES = [("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")]

    execution = models.ForeignKey(AgentExecution, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=20, choices=KINDS)
    agent_id = models.CharField(max_length=40, choices=AgentExecution.AGENT_IDS)
    status = models.CharField(max_length=12, choices=STATUSES, default="running")
    input_references = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    tool_call_count = models.PositiveSmallIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [models.UniqueConstraint(
            fields=["execution", "sequence"],
            name="uniq_agent_step_execution_sequence",
        )]
        indexes = [models.Index(fields=["execution", "status"], name="agent_step_exec_status_idx")]


class PredictiveEvaluationRun(TimestampedModel):
    """Persisted, chronological model evaluation; does not mutate supply-chain records."""

    MODEL_TYPES = [
        ("shipment_delay", "Shipment delay"),
        ("material_demand", "Material demand"),
    ]
    STATUSES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("insufficient_data", "Insufficient data"),
        ("failed", "Failed"),
    ]

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ares_predictive_evaluations",
    )
    model_type = models.CharField(max_length=24, choices=MODEL_TYPES)
    status = models.CharField(max_length=20, choices=STATUSES, default="running")
    model_version = models.CharField(max_length=120)
    as_of_date = models.DateField()
    holdout_start_date = models.DateField(null=True, blank=True)
    holdout_end_date = models.DateField(null=True, blank=True)
    sample_count = models.PositiveIntegerField(default=0)
    data_fingerprint = models.CharField(max_length=64, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["model_type", "status"], name="pred_eval_type_status_idx"),
            models.Index(fields=["created_at"], name="pred_eval_created_idx"),
        ]


class ShipmentRiskPredictionSnapshot(TimestampedModel):
    """Immutable point-in-time shipment prediction retained for later verified scoring."""
    prediction_fingerprint = models.CharField(max_length=64)
    shipment = models.ForeignKey(
        Shipment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="risk_prediction_snapshots",
    )
    shipment_reference = models.CharField(max_length=50)
    purchase_order_number = models.CharField(max_length=40)
    supplier_code = models.CharField(max_length=40)
    supplier_name = models.CharField(max_length=180)
    eta_at_prediction = models.DateField()
    model_version = models.CharField(max_length=120)
    training_cutoff_date = models.DateField()
    late_probability_percent = models.DecimalField(max_digits=5, decimal_places=1)
    model_confidence_percent = models.DecimalField(max_digits=5, decimal_places=1)
    expected_delay_days = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    delay_range_low_days = models.PositiveSmallIntegerField(null=True, blank=True)
    delay_range_high_days = models.PositiveSmallIntegerField(null=True, blank=True)
    feature_snapshot = models.JSONField(default=dict, blank=True)
    factors = models.JSONField(default=list, blank=True)
    material_shortage = models.JSONField(default=dict, blank=True)
    captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ares_shipment_prediction_snapshots",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["shipment", "created_at"], name="ship_pred_snap_date_idx"),
            models.Index(fields=["model_version", "created_at"], name="ship_pred_model_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shipment", "prediction_fingerprint"],
                name="unique_shipment_pred_hash",
            ),
            models.CheckConstraint(
                condition=Q(late_probability_percent__gte=0, late_probability_percent__lte=100),
                name="ship_pred_probability_range",
            ),
            models.CheckConstraint(
                condition=Q(model_confidence_percent__gte=0, model_confidence_percent__lte=100),
                name="ship_pred_confidence_range",
            ),
            models.CheckConstraint(
                condition=Q(expected_delay_days__isnull=True) | Q(expected_delay_days__gte=0),
                name="ship_pred_delay_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(delay_range_low_days__isnull=True, delay_range_high_days__isnull=True)
                    | Q(delay_range_low_days__isnull=False, delay_range_high_days__isnull=False,
                        delay_range_high_days__gte=models.F("delay_range_low_days"))
                ),
                name="ship_pred_delay_range_valid",
            ),
        ]

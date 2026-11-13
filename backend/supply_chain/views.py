import json
import logging
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import F, Q
from django.db.utils import DatabaseError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import (
    AuditEvent, Disruption, ExternalFeed, ExternalFeedEvent, Inventory, InventoryMovement, Material, PurchaseOrder,
    NotificationDelivery, PurchaseOrderLine, ResponseAction, ResponsePlan,
    ResponseActionExecution, RiskAlert, RiskAssessmentSnapshot, RiskOutcome,
    Shipment, Supplier, Warehouse,
)
from .predictive_risk import predictive_risk_report
from .demand_forecast import demand_forecast_report
from .risk_workflow import assess_and_record, risk_calibration_report, risk_configuration
from .action_execution import execute_action
from .notifications import queue_action_notification, queue_plan_notification
from .serializers import (
    AuditEventSerializer, DisruptionSerializer, InventoryMovementSerializer,
    InventorySerializer, MaterialSerializer, PurchaseOrderLineSerializer,
    PurchaseOrderSerializer, CancellationReasonSerializer, OutcomeSerializer,
    RejectionNotesSerializer, ResponseActionSerializer, ResponsePlanSerializer,
    RiskAlertSerializer, RiskAssessmentSnapshotSerializer, RiskOutcomeSerializer,
    RiskOutcomeUpsertSerializer, NotificationDeliverySerializer,
    DeliveryOutcomeVerificationSerializer,
    ResponseActionExecutionRequestSerializer, ResponseActionExecutionSerializer,
    ReviewNotesSerializer,
    ShipmentSerializer, SupplierSerializer, WarehouseSerializer,
)
from .permissions import IsSupplyChainApprover
from .gdacs_feed import FEED_KEY
from .geospatial import MAX_EVENT_GEOMETRY_POSITIONS, MAX_ROUTE_GEOMETRY_POSITIONS, normalize_geojson_geometry

logger = logging.getLogger("ares.api")
MAX_MAP_SHIPMENTS = 2000
MAX_MAP_EVENTS = 500


def _reviewer_identity(user):
    display_name = user.get_full_name().strip()
    return display_name if display_name and len(display_name) <= 150 else user.get_username()


def _map_geometry(value, allowed_types, max_positions):
    if not isinstance(value, dict):
        return None
    try:
        return normalize_geojson_geometry(value, allowed_types=allowed_types, max_positions=max_positions)
    except (TypeError, ValueError):
        return None


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

    @action(
        detail=True,
        methods=["post"],
        url_path="verify-delivery",
        permission_classes=[IsSupplyChainApprover],
    )
    def verify_delivery(self, request, pk=None):
        shipment = self.get_object()
        if shipment.status != "delivered":
            raise ValidationError({"status": "Mark the shipment delivered before verifying its outcome."})
        serializer = DeliveryOutcomeVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actual_date = serializer.validated_data["actual_delivery_date"]
        order_date = shipment.purchase_order.ordered_at or shipment.purchase_order.created_at.date()
        if actual_date > timezone.localdate():
            raise ValidationError({"actual_delivery_date": "A verified actual delivery date cannot be in the future."})
        if actual_date < order_date:
            raise ValidationError({"actual_delivery_date": "Actual delivery cannot be earlier than the purchase-order date."})

        before = self._snapshot(shipment)
        shipment.actual_delivery_date = actual_date
        shipment.delivery_outcome_verified = True
        shipment.delivery_outcome_verified_at = timezone.now()
        shipment.delivery_outcome_verified_by = _reviewer_identity(request.user)
        shipment.delivery_outcome_evidence = serializer.validated_data["evidence_notes"]
        shipment.save(update_fields=[
            "actual_delivery_date", "delivery_outcome_verified", "delivery_outcome_verified_at",
            "delivery_outcome_verified_by", "delivery_outcome_evidence", "updated_at",
        ])
        self._audit(shipment, "update", before=before, after=self._snapshot(shipment))
        return Response(self.get_serializer(shipment).data)


class DisruptionViewSet(AuditedModelViewSet):
    queryset = Disruption.objects.select_related("affected_supplier", "affected_shipment").all()
    serializer_class = DisruptionSerializer

    def perform_destroy(self, instance):
        if instance.response_plans.exists():
            raise ValidationError("This disruption has response plans; retain the linked audit history instead of deleting it.")
        super().perform_destroy(instance)


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditEvent.objects.all()
    serializer_class = AuditEventSerializer


class RiskAssessmentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RiskAssessmentSnapshotSerializer

    def get_queryset(self):
        queryset = RiskAssessmentSnapshot.objects.select_related("disruption", "source_event").all()
        disruption_id = self.request.query_params.get("disruption_id")
        return queryset.filter(disruption_id=disruption_id) if disruption_id else queryset


class RiskAlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RiskAlertSerializer

    def get_queryset(self):
        queryset = RiskAlert.objects.select_related("disruption", "latest_assessment").all()
        alert_status = self.request.query_params.get("status")
        disruption_id = self.request.query_params.get("disruption_id")
        if alert_status in {"active", "cleared"}:
            queryset = queryset.filter(status=alert_status)
        if disruption_id:
            queryset = queryset.filter(disruption_id=disruption_id)
        return queryset


class NotificationDeliveryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationDeliverySerializer

    def get_queryset(self):
        queryset = NotificationDelivery.objects.all()
        user = self.request.user
        can_view_outbox = user.is_staff or user.groups.filter(name="ares_approvers").exists()
        if not can_view_outbox and not user.email:
            return queryset.none()
        if not can_view_outbox:
            queryset = queryset.filter(recipient_email__iexact=user.email)
        delivery_status = self.request.query_params.get("status")
        if delivery_status in {"pending", "sending", "retry", "sent", "failed", "unroutable"}:
            queryset = queryset.filter(status=delivery_status)
        return queryset.order_by("-created_at")


class ResponsePlanViewSet(AuditMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                          mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = ResponsePlan.objects.select_related("disruption", "created_by").prefetch_related("actions__executions").all()
    serializer_class = ResponsePlanSerializer

    def get_permissions(self):
        if self.action in {"approve", "reject"}:
            return [IsSupplyChainApprover()]
        return super().get_permissions()

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        self._audit(instance, "create", after=self._snapshot(instance))

    @transaction.atomic
    def _change_plan(self, plan_id, transition, event_type, notification_text):
        plan = get_object_or_404(
            ResponsePlan.objects.select_for_update(of=("self",)).select_related("disruption", "created_by").prefetch_related("actions__executions"),
            pk=plan_id,
        )
        before = self._snapshot(plan)
        update_fields = transition(plan)
        plan.save(update_fields=[*update_fields, "updated_at"])
        self._audit(plan, "update", before=before, after=self._snapshot(plan))
        queue_plan_notification(plan, event_type, notification_text)
        return plan

    def _transition_response(self, plan_id, transition, event_type, notification_text):
        plan = self._change_plan(plan_id, transition, event_type, notification_text)
        return Response(self.get_serializer(plan).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        def transition(plan):
            if plan.status not in {"draft", "rejected"}:
                raise ValidationError({"status": "Only a draft or rejected plan can be submitted for approval."})
            if not plan.actions.exists():
                raise ValidationError({"actions": "Add at least one action item before submitting the plan."})
            plan.status = "pending_approval"
            plan.submitted_at = timezone.now()
            plan.reviewed_by = ""
            plan.reviewed_at = None
            plan.review_notes = ""
            return ["status", "submitted_at", "reviewed_by", "reviewed_at", "review_notes"]

        return self._transition_response(pk, transition, "plan_submitted", "Plan submitted for approver review.")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        serializer = ReviewNotesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reviewer = _reviewer_identity(request.user)
        notes = serializer.validated_data.get("review_notes", "").strip()

        def transition(plan):
            if plan.status != "pending_approval":
                raise ValidationError({"status": "Only a plan pending approval can be approved."})
            plan.status = "approved"
            plan.reviewed_by = reviewer
            plan.reviewed_at = timezone.now()
            plan.review_notes = notes
            return ["status", "reviewed_by", "reviewed_at", "review_notes"]

        return self._transition_response(pk, transition, "plan_approved", "Plan approved by an ARES approver.")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        serializer = RejectionNotesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reviewer = _reviewer_identity(request.user)
        notes = serializer.validated_data["review_notes"].strip()

        def transition(plan):
            if plan.status != "pending_approval":
                raise ValidationError({"status": "Only a plan pending approval can be rejected."})
            plan.status = "rejected"
            plan.reviewed_by = reviewer
            plan.reviewed_at = timezone.now()
            plan.review_notes = notes
            return ["status", "reviewed_by", "reviewed_at", "review_notes"]

        return self._transition_response(pk, transition, "plan_rejected", "Plan was returned with a review decision.")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        def transition(plan):
            if plan.status != "approved":
                raise ValidationError({"status": "A plan must be approved before work can start."})
            plan.status = "active"
            return ["status"]

        return self._transition_response(pk, transition, "plan_started", "Approved response work has started.")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        serializer = OutcomeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        outcome = serializer.validated_data["outcome"].strip()

        def transition(plan):
            if plan.status != "active":
                raise ValidationError({"status": "Only an active plan can be completed."})
            unfinished = plan.actions.exclude(status__in=["completed", "cancelled"]).exists()
            if unfinished:
                raise ValidationError({"actions": "Complete or cancel every action item before completing the plan."})
            plan.status = "completed"
            plan.outcome = outcome
            plan.completed_at = timezone.now()
            return ["status", "outcome", "completed_at"]

        return self._transition_response(pk, transition, "plan_completed", "Response plan was completed with a recorded outcome.")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = CancellationReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"].strip()

        def transition(plan):
            if plan.status in {"completed", "cancelled"}:
                raise ValidationError({"status": "A completed or cancelled plan cannot be cancelled again."})
            plan.status = "cancelled"
            plan.outcome = reason
            return ["status", "outcome"]

        return self._transition_response(pk, transition, "plan_cancelled", "Response plan was cancelled with a recorded reason.")


class ResponseActionViewSet(AuditMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                            mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = ResponseAction.objects.select_related("plan", "plan__disruption", "plan__created_by").prefetch_related("executions").all()
    serializer_class = ResponseActionSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    @transaction.atomic
    def perform_update(self, serializer):
        super().perform_update(serializer)
        queue_action_notification(serializer.instance)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        serializer = ResponseActionExecutionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dry_run = serializer.validated_data["dry_run"]
        if not dry_run and not IsSupplyChainApprover().has_permission(request, self):
            raise PermissionDenied(IsSupplyChainApprover.message)
        execution, replay = execute_action(
            pk,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            requested_by=_reviewer_identity(request.user),
            live=not dry_run,
        )
        http_status = status.HTTP_502_BAD_GATEWAY if execution.status == "failed" else (
            status.HTTP_202_ACCEPTED if execution.status == "running" else status.HTTP_200_OK
        )
        return Response({
            "execution": ResponseActionExecutionSerializer(execution).data,
            "idempotent_replay": replay,
        }, status=http_status)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    try:
        connection.ensure_connection()
    except DatabaseError:
        logger.exception("ARES database health check failed")
        return Response(
            {"status": "error", "service": "ARES API", "database": "unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"status": "ok", "service": "ARES API", "database": "PostgreSQL"})


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
        "active_risk_alerts": RiskAlert.objects.filter(status="active").count(),
    })


@api_view(["GET"])
def map_data(request):
    """Return shipment coordinates and current located GDACS events for the network map."""
    shipment_query = Shipment.objects.select_related("purchase_order").order_by("eta", "reference")
    shipment_total = shipment_query.count()
    shipment_rows = list(shipment_query[:MAX_MAP_SHIPMENTS])
    shipments = [{
        "id": str(shipment.pk),
        "reference": shipment.reference,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "origin_latitude": float(shipment.origin_latitude) if shipment.origin_latitude is not None else None,
        "origin_longitude": float(shipment.origin_longitude) if shipment.origin_longitude is not None else None,
        "destination_latitude": float(shipment.destination_latitude) if shipment.destination_latitude is not None else None,
        "destination_longitude": float(shipment.destination_longitude) if shipment.destination_longitude is not None else None,
        "route_geometry": _map_geometry(
            shipment.route_geometry, {"LineString", "MultiLineString"}, MAX_ROUTE_GEOMETRY_POSITIONS,
        ),
        "route_geometry_source": shipment.route_geometry_source,
        "carrier": shipment.carrier,
        "eta": shipment.eta,
        "status": shipment.status,
        "risk_score": shipment.risk_score,
    } for shipment in shipment_rows]

    now = timezone.now()
    event_query = ExternalFeedEvent.objects.filter(
        feed__key=FEED_KEY,
        lifecycle="active",
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
    ).order_by("-issued_at", "-created_at")
    event_total = event_query.count()
    event_rows = list(event_query[:MAX_MAP_EVENTS])
    disasters = []
    for event in event_rows:
        payload = event.payload if isinstance(event.payload, dict) else {}
        alert_level = str(payload.get("alert_level", "")).casefold()
        if alert_level not in {"green", "orange", "red"}:
            alert_level = {"low": "green", "high": "orange", "critical": "red"}.get(event.severity, "green")
        point = payload.get("point")
        latitude = longitude = None
        if isinstance(point, str) and "," in point:
            try:
                latitude_text, longitude_text = point.split(",", 1)
                latitude, longitude = float(latitude_text), float(longitude_text)
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    latitude = longitude = None
            except (TypeError, ValueError):
                latitude = longitude = None
        geometry = _map_geometry(
            payload.get("geometry"), {"Point", "Polygon", "MultiPolygon"}, MAX_EVENT_GEOMETRY_POSITIONS,
        )
        geometry_status = payload.get("geometry_status", "missing")
        if geometry:
            geometry_status = "valid"
        elif geometry_status == "valid":
            geometry_status = "invalid"
        disasters.append({
            "id": str(event.pk),
            "title": event.title,
            "event_type": event.event_type,
            "alert_level": alert_level,
            "affected_region": event.affected_region,
            "issued_at": event.issued_at,
            "expires_at": event.expires_at,
            "latitude": latitude,
            "longitude": longitude,
            "geometry": geometry,
            "geometry_status": geometry_status,
            "source_event_id": payload.get("event_id", ""),
            "episode_id": payload.get("episode_id", ""),
            "source_metrics": payload.get("source_metrics", {}) if isinstance(payload.get("source_metrics"), dict) else {},
            "source_url": _safe_gdacs_url(payload.get("link", "")),
        })

    feed = ExternalFeed.objects.filter(key=FEED_KEY).first()
    return Response({
        "generated_at": now,
        "shipments": shipments,
        "disasters": disasters,
        "feed": {
            "status": feed.status if feed else "never",
            "last_success_at": feed.last_success_at if feed else None,
            "last_error": feed.last_error if feed else "",
        },
        "counts": {
            "shipments_total": shipment_total,
            "shipments_returned": len(shipments),
            "shipments_truncated": shipment_total > MAX_MAP_SHIPMENTS,
            "shipments_with_coordinates": sum(
                shipment["origin_latitude"] is not None or shipment["destination_latitude"] is not None
                for shipment in shipments
            ),
            "shipments_with_route_geometry": sum(bool(shipment["route_geometry"]) for shipment in shipments),
            "disasters_total": event_total,
            "disasters_returned": len(disasters),
            "disasters_truncated": event_total > MAX_MAP_EVENTS,
            "disasters_with_coordinates": sum(event["latitude"] is not None or event["geometry"] is not None for event in disasters),
        },
    })


def _safe_gdacs_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme.casefold() != "https" or not (hostname == "gdacs.org" or hostname.endswith(".gdacs.org")):
            return ""
        return value
    except ValueError:
        return ""


@api_view(["POST"])
def risk_assess(request):
    disruption_id = request.data.get("disruption_id") if hasattr(request.data, "get") else None
    if disruption_id:
        try:
            disruption = Disruption.objects.select_related("affected_supplier", "affected_shipment").get(pk=disruption_id)
        except (Disruption.DoesNotExist, ValueError, TypeError, DjangoValidationError):
            return Response({"detail": "Disruption not found."}, status=status.HTTP_404_NOT_FOUND)
    else:
        serializer = DisruptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        disruption = serializer.save()
        disruption = Disruption.objects.select_related("affected_supplier", "affected_shipment").get(pk=disruption.pk)
    result, snapshot = assess_and_record(disruption, trigger="manual")
    return Response({**result, "assessment_id": str(snapshot.pk), "assessed_at": snapshot.created_at})


@api_view(["GET", "POST"])
@permission_classes([IsSupplyChainApprover])
def risk_outcome_upsert(request):
    if request.method == "GET":
        outcomes = RiskOutcome.objects.select_related("disruption").all()
        return Response(RiskOutcomeSerializer(outcomes, many=True).data)

    serializer = RiskOutcomeUpsertSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    disruption = get_object_or_404(Disruption, pk=values["disruption_id"])
    reviewer = _reviewer_identity(request.user)
    existing = RiskOutcome.objects.filter(disruption=disruption).first()
    before = (
        json.loads(json.dumps(RiskOutcomeSerializer(existing).data, cls=DjangoJSONEncoder))
        if existing else None
    )
    outcome, created = RiskOutcome.objects.update_or_create(
        disruption=disruption,
        defaults={
            "outcome": values["outcome"],
            "reviewed_by": reviewer,
            "evidence_notes": values.get("evidence_notes", "").strip(),
            "reviewed_at": timezone.now(),
        },
    )
    after = json.loads(json.dumps(RiskOutcomeSerializer(outcome).data, cls=DjangoJSONEncoder))
    AuditEvent.objects.create(
        entity_type="supply_chain.riskoutcome",
        entity_id=str(outcome.pk),
        action="create" if created else "update",
        actor=reviewer,
        changes={"before": before, "after": after},
    )
    return Response(RiskOutcomeSerializer(outcome).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
def risk_calibration(request):
    return Response(risk_calibration_report())


@api_view(["GET"])
def predictive_risk(request):
    return Response(predictive_risk_report())


@api_view(["GET"])
def inventory_forecast(request):
    return Response(demand_forecast_report())


@api_view(["GET"])
def risk_policy(request):
    configuration = risk_configuration()
    return Response({
        **configuration,
        "risk_bands": {"low": [0, 34], "moderate": [35, 59], "high": [60, 79], "critical": [80, 100]},
        "notifications_delivered": False,
        "governance": "Alerts are advisory records. Operational actions remain subject to human review and Phase 5 delivery controls.",
    })

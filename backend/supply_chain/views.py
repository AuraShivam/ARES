import json
import logging
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import F
from django.db.utils import DatabaseError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import (
    AuditEvent, Disruption, Inventory, InventoryMovement, Material, PurchaseOrder,
    NotificationDelivery, PurchaseOrderLine, ResponseAction, ResponsePlan,
    ResponseActionExecution, RiskAlert, RiskAssessmentSnapshot, RiskOutcome,
    Shipment, Supplier, Warehouse,
)
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
    ResponseActionExecutionRequestSerializer, ResponseActionExecutionSerializer,
    ReviewNotesSerializer,
    ShipmentSerializer, SupplierSerializer, WarehouseSerializer,
)
from .permissions import IsSupplyChainApprover

logger = logging.getLogger("ares.api")


def _reviewer_identity(user):
    display_name = user.get_full_name().strip()
    return display_name if display_name and len(display_name) <= 150 else user.get_username()


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


@api_view(["POST"])
@permission_classes([IsSupplyChainApprover])
def risk_outcome_upsert(request):
    serializer = RiskOutcomeUpsertSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    disruption = get_object_or_404(Disruption, pk=values["disruption_id"])
    reviewer = _reviewer_identity(request.user)
    existing = RiskOutcome.objects.filter(disruption=disruption).first()
    before = RiskOutcomeSerializer(existing).data if existing else None
    outcome, created = RiskOutcome.objects.update_or_create(
        disruption=disruption,
        defaults={
            "outcome": values["outcome"],
            "reviewed_by": reviewer,
            "evidence_notes": values.get("evidence_notes", "").strip(),
            "reviewed_at": timezone.now(),
        },
    )
    AuditEvent.objects.create(
        entity_type="supply_chain.riskoutcome",
        entity_id=str(outcome.pk),
        action="create" if created else "update",
        actor=reviewer,
        changes={"before": before, "after": RiskOutcomeSerializer(outcome).data},
    )
    return Response(RiskOutcomeSerializer(outcome).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
def risk_calibration(request):
    return Response(risk_calibration_report())


@api_view(["GET"])
def risk_policy(request):
    configuration = risk_configuration()
    return Response({
        **configuration,
        "risk_bands": {"low": [0, 34], "moderate": [35, 59], "high": [60, 79], "critical": [80, 100]},
        "notifications_delivered": False,
        "governance": "Alerts are advisory records. Operational actions remain subject to human review and Phase 5 delivery controls.",
    })

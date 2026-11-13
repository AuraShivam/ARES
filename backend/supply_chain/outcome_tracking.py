"""Persist and review point-in-time shipment predictions and outcomes."""

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.throttling import UserRateThrottle

from .models import AuditEvent, Shipment, ShipmentRiskPredictionSnapshot
from .permissions import IsSupplyChainApprover
from .predictive_risk import predictive_risk_report
from .serializers import ShipmentRiskPredictionSnapshotSerializer


class ShipmentPredictionCaptureRequestSerializer(serializers.Serializer):
    shipment_id = serializers.UUIDField()


class ShipmentPredictionCaptureThrottle(UserRateThrottle):
    scope = "shipment_prediction_capture"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ShipmentPredictionCaptureThrottle])
def shipment_prediction_snapshots(request):
    if request.method == "GET":
        if not IsSupplyChainApprover().has_permission(request, None):
            raise PermissionDenied("Prediction history is available to ARES approvers.")
        rows = ShipmentRiskPredictionSnapshot.objects.select_related("shipment", "captured_by")
        shipment_id = request.query_params.get("shipment_id")
        if shipment_id:
            try:
                shipment_id = UUID(shipment_id)
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError({"shipment_id": "Provide a valid shipment UUID."}) from exc
            rows = rows.filter(shipment_id=shipment_id)
        rows = rows.order_by("-created_at")
        total = rows.count()
        page_rows = list(rows[:100])
        return Response({"count": total, "results": ShipmentRiskPredictionSnapshotSerializer(page_rows, many=True).data})

    serializer = ShipmentPredictionCaptureRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    shipment = get_object_or_404(
        Shipment.objects.select_related("purchase_order", "purchase_order__supplier"),
        pk=serializer.validated_data["shipment_id"],
    )
    if shipment.status not in {"planned", "in_transit", "delayed", "at_risk"} or shipment.eta is None:
        raise serializers.ValidationError({"shipment_id": "Only an open shipment with a promised ETA can be captured."})

    report = predictive_risk_report(shipment_id=shipment.pk)
    if not report.get("predictions_available"):
        return Response({
            "detail": report.get("readiness_message", "Shipment prediction is unavailable for the current training data."),
            "training_status": report.get("training_status"),
            "verified_shipments_used": report.get("verified_shipments_used"),
        }, status=status.HTTP_409_CONFLICT)
    prediction = next((item for item in report["predictions"] if item["shipment_id"] == str(shipment.pk)), None)
    if prediction is None:
        return Response({"detail": "No current prediction was produced for this shipment."}, status=status.HTTP_409_CONFLICT)

    delay_range = prediction.get("expected_delay_range_days")
    fingerprint_data = {
        "shipment_id": str(shipment.pk),
        "eta": shipment.eta.isoformat(),
        "model_version": report["model_version"],
        "training_cutoff_date": report["training_cutoff_date"],
        "late_probability_percent": prediction["late_probability_percent"],
        "model_confidence_percent": prediction["model_confidence_percent"],
        "expected_delay_days": prediction.get("expected_delay_days"),
        "expected_delay_range_days": delay_range,
        "feature_snapshot": prediction.get("feature_snapshot") or {},
        "factors": prediction.get("factors") or [],
        "material_shortage": prediction.get("material_shortage") or {},
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    snapshot, created = ShipmentRiskPredictionSnapshot.objects.get_or_create(
        shipment=shipment,
        prediction_fingerprint=fingerprint,
        defaults={
            "shipment_reference": shipment.reference,
            "purchase_order_number": shipment.purchase_order.number,
            "supplier_code": shipment.purchase_order.supplier.code,
            "supplier_name": shipment.purchase_order.supplier.name,
            "eta_at_prediction": shipment.eta,
            "model_version": report["model_version"],
            "training_cutoff_date": report["training_cutoff_date"],
            "late_probability_percent": Decimal(str(prediction["late_probability_percent"])),
            "model_confidence_percent": Decimal(str(prediction["model_confidence_percent"])),
            "expected_delay_days": (Decimal(str(prediction["expected_delay_days"]))
                                     if prediction.get("expected_delay_days") is not None else None),
            "delay_range_low_days": delay_range[0] if delay_range else None,
            "delay_range_high_days": delay_range[1] if delay_range else None,
            "feature_snapshot": prediction.get("feature_snapshot") or {},
            "factors": prediction.get("factors") or [],
            "material_shortage": prediction.get("material_shortage") or {},
            "captured_by": request.user,
        },
    )
    if created:
        AuditEvent.objects.create(
            entity_type="supply_chain.shipmentriskpredictionsnapshot",
            entity_id=str(snapshot.pk),
            action="create",
            actor=request.user.get_username(),
            changes={
                "before": None,
                "after": {
                    "shipment_id": str(shipment.pk),
                    "shipment_reference": snapshot.shipment_reference,
                    "eta_at_prediction": snapshot.eta_at_prediction.isoformat(),
                    "model_version": snapshot.model_version,
                    "training_cutoff_date": snapshot.training_cutoff_date.isoformat(),
                    "late_probability_percent": str(snapshot.late_probability_percent),
                    "prediction_fingerprint": snapshot.prediction_fingerprint,
                },
            },
        )
    return Response(
        ShipmentRiskPredictionSnapshotSerializer(snapshot).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )

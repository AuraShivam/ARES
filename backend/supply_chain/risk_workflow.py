"""Persist explainable risk assessments and maintain deduplicated alert state."""

import os
from datetime import timedelta

from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import AuditEvent, Disruption, RiskAlert, RiskAssessmentSnapshot, RiskOutcome
from .notifications import queue_risk_alert_notification
from .risk import assess


BAND_RANK = {"low": 0, "moderate": 1, "high": 2, "critical": 3}


def risk_configuration():
    """Read safe, non-secret alert policy values from the process environment."""
    raw_threshold = os.getenv("ARES_RISK_ALERT_SCORE_THRESHOLD", "60").strip()
    raw_cooldown = os.getenv("ARES_RISK_ALERT_COOLDOWN_MINUTES", "60").strip()
    try:
        threshold = int(raw_threshold)
    except ValueError as exc:
        raise ValidationError("ARES_RISK_ALERT_SCORE_THRESHOLD must be a whole number from 0 to 100.") from exc
    try:
        cooldown_minutes = int(raw_cooldown)
    except ValueError as exc:
        raise ValidationError("ARES_RISK_ALERT_COOLDOWN_MINUTES must be a whole number of minutes.") from exc
    if not 0 <= threshold <= 100:
        raise ValidationError("ARES_RISK_ALERT_SCORE_THRESHOLD must be between 0 and 100.")
    if cooldown_minutes < 0:
        raise ValidationError("ARES_RISK_ALERT_COOLDOWN_MINUTES cannot be negative.")
    return {"alert_score_threshold": threshold, "cooldown_minutes": cooldown_minutes}


def risk_calibration_report():
    """Compare the latest score per disruption with approver-entered outcomes."""
    configuration = risk_configuration()
    latest = RiskAssessmentSnapshot.objects.filter(
        disruption_id=OuterRef("disruption_id"),
    ).order_by("-created_at")
    labels = RiskOutcome.objects.annotate(
        latest_score=Subquery(latest.values("risk_score")[:1]),
        latest_band=Subquery(latest.values("risk_band")[:1]),
    ).values("outcome", "latest_score", "latest_band")
    by_band = {}
    confusion = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    labeled_without_assessment = 0
    sample_count = 0
    for row in labels.iterator():
        sample_count += 1
        if row["latest_score"] is None:
            labeled_without_assessment += 1
            continue
        band = row["latest_band"] or "unknown"
        bucket = by_band.setdefault(band, {"confirmed_impact": 0, "no_material_impact": 0})
        positive = row["outcome"] == "impact"
        bucket["confirmed_impact" if positive else "no_material_impact"] += 1
        predicted_positive = row["latest_score"] >= configuration["alert_score_threshold"]
        confusion[
            ("true_positive" if positive else "false_positive")
            if predicted_positive
            else ("false_negative" if positive else "true_negative")
        ] += 1

    for bucket in by_band.values():
        total = bucket["confirmed_impact"] + bucket["no_material_impact"]
        bucket["labeled_cases"] = total
        bucket["observed_impact_rate_percent"] = round(bucket["confirmed_impact"] * 100 / total, 1) if total else None
    assessed_labeled = sum(bucket["labeled_cases"] for bucket in by_band.values())
    true_positive = confusion["true_positive"]
    false_positive = confusion["false_positive"]
    false_negative = confusion["false_negative"]
    return {
        "method": "descriptive comparison of the latest assessment per disruption against approver-reviewed outcomes",
        "is_empirically_calibrated": False,
        "alert_score_threshold": configuration["alert_score_threshold"],
        "labeled_cases": sample_count,
        "assessed_labeled_cases": assessed_labeled,
        "labeled_without_assessment": labeled_without_assessment,
        "by_risk_band": by_band,
        "threshold_confusion_matrix": confusion,
        "precision_percent": round(true_positive * 100 / (true_positive + false_positive), 1) if true_positive + false_positive else None,
        "recall_percent": round(true_positive * 100 / (true_positive + false_negative), 1) if true_positive + false_negative else None,
        "limitations": "This report describes the entered labels; sample sizes may be small and scoring rules are not trained or auto-adjusted.",
    }


def _snapshot(disruption, result, trigger, source_event):
    return RiskAssessmentSnapshot.objects.create(
        disruption=disruption,
        source_event=source_event,
        trigger=trigger,
        risk_score=result["risk_score"],
        risk_band=result["risk_band"],
        confidence=result["confidence"],
        model_version=result["model"],
        score_breakdown=result["score_breakdown"],
        factors=result["factors"],
        evidence=result["evidence"],
        recommendation=result["recommendation"],
    )


def _audit_alert(alert, action, before=None):
    AuditEvent.objects.create(
        entity_type="supply_chain.riskalert",
        entity_id=str(alert.pk),
        action=action,
        actor="risk-engine",
        changes={
            "before": before,
            "after": {
                "disruption_id": str(alert.disruption_id),
                "status": alert.status,
                "risk_score": alert.risk_score,
                "risk_band": alert.risk_band,
                "threshold_score": alert.threshold_score,
                "notification_due": alert.notification_due,
                "alert_generation_count": alert.alert_generation_count,
            },
        },
    )


def _maintain_alert(disruption, assessment, result, configuration, now):
    threshold = configuration["alert_score_threshold"]
    active = RiskAlert.objects.select_for_update().filter(
        disruption=disruption, status="active",
    ).first()

    if result["risk_score"] < threshold or disruption.status == "resolved":
        if active:
            before = {"status": active.status, "risk_score": active.risk_score, "risk_band": active.risk_band}
            active.status = "cleared"
            active.resolved_at = now
            active.notification_due = False
            active.latest_assessment = assessment
            active.risk_score = result["risk_score"]
            active.risk_band = result["risk_band"]
            active.save(update_fields=[
                "status", "resolved_at", "notification_due", "latest_assessment",
                "risk_score", "risk_band", "updated_at",
            ])
            _audit_alert(active, "update", before=before)
            queue_risk_alert_notification(active, cleared=True)
        return

    if active is None:
        alert = RiskAlert.objects.create(
            disruption=disruption,
            latest_assessment=assessment,
            risk_score=result["risk_score"],
            risk_band=result["risk_band"],
            threshold_score=threshold,
            first_triggered_at=now,
            last_triggered_at=now,
            notification_due=True,
        )
        _audit_alert(alert, "create")
        queue_risk_alert_notification(alert, generation=alert.alert_generation_count)
        alert.notification_due = False
        alert.save(update_fields=["notification_due", "updated_at"])
        return

    before = {"risk_score": active.risk_score, "risk_band": active.risk_band}
    prior_band_rank = BAND_RANK.get(active.risk_band, 0)
    new_band_rank = BAND_RANK.get(result["risk_band"], 0)
    threshold_changed = active.threshold_score != threshold
    active.latest_assessment = assessment
    active.risk_score = result["risk_score"]
    active.risk_band = result["risk_band"]
    active.threshold_score = threshold
    active.deduplicated_count += 1

    cooldown = timedelta(minutes=configuration["cooldown_minutes"])
    cooldown_elapsed = now >= active.last_triggered_at + cooldown
    escalated = new_band_rank > prior_band_rank
    generated = escalated or cooldown_elapsed or threshold_changed
    if generated:
        active.notification_due = True
        active.alert_generation_count += 1
        active.last_triggered_at = now
    else:
        active.cooldown_suppressed_count += 1

    active.save(update_fields=[
        "latest_assessment", "risk_score", "risk_band", "threshold_score", "deduplicated_count",
        "notification_due", "alert_generation_count", "last_triggered_at",
        "cooldown_suppressed_count", "updated_at",
    ])
    if generated:
        queue_risk_alert_notification(active, generation=active.alert_generation_count)
        active.notification_due = False
        active.save(update_fields=["notification_due", "updated_at"])
        _audit_alert(active, "update", before=before)


@transaction.atomic
def assess_and_record(disruption, *, trigger="manual", source_event=None):
    """Reassess under a row lock, persist the evidence, and update alert state."""
    if trigger not in {"manual", "source_event"}:
        raise ValidationError("Unsupported risk assessment trigger.")
    if trigger == "source_event" and source_event is None:
        raise ValidationError("A source-event assessment must reference its source event.")

    current = Disruption.objects.select_for_update(of=("self",)).select_related(
        "affected_supplier", "affected_shipment__purchase_order__supplier",
    ).get(pk=disruption.pk)
    configuration = risk_configuration()
    result = assess(current)
    assessment = _snapshot(current, result, trigger, source_event)
    _maintain_alert(current, assessment, result, configuration, timezone.now())
    return result, assessment

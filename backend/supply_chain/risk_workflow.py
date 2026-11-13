"""Persist explainable risk assessments and maintain deduplicated alert state."""

import os
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    AuditEvent, Disruption, ResponseAction, ResponsePlan, ResponsePlanEffectivenessReview,
    RiskAlert, RiskAssessmentSnapshot, RiskOutcome, Shipment, ShipmentRiskPredictionSnapshot,
)
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
    """Compare point-linked risk/prediction snapshots with reviewed outcomes."""
    configuration = risk_configuration()
    labels = RiskOutcome.objects.select_related("assessment_snapshot").values(
        "outcome", "intervention_status", "assessment_snapshot__risk_score",
        "assessment_snapshot__risk_band",
    )
    by_band = {}
    confusion = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    labeled_without_assessment = 0
    intervention_breakdown = {key: 0 for key, _label in RiskOutcome.INTERVENTION}
    sample_count = 0
    for row in labels.iterator():
        sample_count += 1
        intervention_breakdown[row["intervention_status"]] += 1
        score = row["assessment_snapshot__risk_score"]
        band = row["assessment_snapshot__risk_band"]
        if score is None:
            labeled_without_assessment += 1
            continue
        if row["intervention_status"] != "none":
            continue
        band = band or "unknown"
        bucket = by_band.setdefault(band, {"confirmed_impact": 0, "no_material_impact": 0})
        positive = row["outcome"] == "impact"
        bucket["confirmed_impact" if positive else "no_material_impact"] += 1
        predicted_positive = score >= configuration["alert_score_threshold"]
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
        "method": "descriptive comparison of the exact linked pre-response assessment snapshot against an approver-reviewed outcome; latest assessments are never substituted",
        "is_empirically_calibrated": False,
        "alert_score_threshold": configuration["alert_score_threshold"],
        "labeled_cases": sample_count,
        "assessed_labeled_cases": assessed_labeled,
        "labeled_without_assessment": labeled_without_assessment,
        "intervention_breakdown": intervention_breakdown,
        "intervened_or_unknown_labels_excluded_from_threshold_metrics": sum(
            count for status_key, count in intervention_breakdown.items() if status_key != "none"
        ),
        "by_risk_band": by_band,
        "threshold_confusion_matrix": confusion,
        "precision_percent": round(true_positive * 100 / (true_positive + false_positive), 1) if true_positive + false_positive else None,
        "recall_percent": round(true_positive * 100 / (true_positive + false_negative), 1) if true_positive + false_negative else None,
        "limitations": "Only exact-linked labels explicitly reviewed as having no intervention enter threshold metrics. Other labels are counted separately because mitigations can alter realized impact. Metrics are descriptive; small samples and selection bias remain, and scoring rules are not trained or auto-adjusted.",
        "shipment_prediction_calibration": shipment_prediction_calibration_report(),
        "response_effectiveness": response_effectiveness_report(),
    }


def shipment_prediction_calibration_report():
    snapshots = ShipmentRiskPredictionSnapshot.objects.select_related("shipment").all()
    tracked_count = snapshots.count()
    probability_bins = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    by_probability = {f"{low}-{min(high, 100)}": {"predictions": 0, "late_outcomes": 0,
                                                  "mean_predicted_late_percent": None,
                                                  "observed_late_percent": None,
                                                  "_probability_total": 0.0}
                      for low, high in probability_bins}
    verified_count = 0
    pending_count = 0
    no_intervention_count = 0
    intervention_counts = {key: 0 for key, _label in Shipment.OUTCOME_INTERVENTION}
    all_errors = []
    unmitigated_errors = []
    delay_range_errors = []
    model_versions = set()
    for snapshot in snapshots.iterator():
        model_versions.add(snapshot.model_version)
        shipment = snapshot.shipment
        if not shipment or not shipment.delivery_outcome_verified or not shipment.actual_delivery_date:
            pending_count += 1
            continue
        verified_count += 1
        intervention = shipment.delivery_outcome_intervention
        intervention_counts[intervention] += 1
        actual_late = int(shipment.actual_delivery_date > snapshot.eta_at_prediction)
        probability = float(snapshot.late_probability_percent) / 100
        error = (probability - actual_late) ** 2
        all_errors.append(error)
        if intervention != "none":
            continue
        no_intervention_count += 1
        delay_days = max(0, (shipment.actual_delivery_date - snapshot.eta_at_prediction).days)
        bucket_key = next(f"{low}-{min(high, 100)}" for low, high in probability_bins
                          if low <= float(snapshot.late_probability_percent) < high)
        bucket = by_probability[bucket_key]
        bucket["predictions"] += 1
        bucket["late_outcomes"] += actual_late
        bucket["_probability_total"] += float(snapshot.late_probability_percent)
        unmitigated_errors.append(error)
        if actual_late and snapshot.delay_range_low_days is not None and snapshot.delay_range_high_days is not None:
            midpoint = (snapshot.delay_range_low_days + snapshot.delay_range_high_days) / 2
            delay_range_errors.append(abs(delay_days - midpoint))

    for bucket in by_probability.values():
        count = bucket["predictions"]
        bucket["mean_predicted_late_percent"] = round(bucket.pop("_probability_total") / count, 1) if count else None
        bucket["observed_late_percent"] = round(bucket["late_outcomes"] * 100 / count, 1) if count else None
    return {
        "tracked_snapshots": tracked_count,
        "verified_outcomes": verified_count,
        "pending_outcomes": pending_count,
        "no_intervention_verified_outcomes": no_intervention_count,
        "intervention_breakdown": intervention_counts,
        "brier_score_all_verified": round(sum(all_errors) / len(all_errors), 4) if all_errors else None,
        "brier_score_no_intervention": round(sum(unmitigated_errors) / len(unmitigated_errors), 4) if unmitigated_errors else None,
        "by_probability_band_no_intervention": by_probability,
        "delay_range_mae_days_no_intervention": round(sum(delay_range_errors) / len(delay_range_errors), 2) if delay_range_errors else None,
        "delay_range_scored_outcomes": len(delay_range_errors),
        "model_versions": sorted(model_versions),
        "limitations": "Brier scores and observed rates are retrospective summaries of captured predictions. The no-intervention subset is reviewer-labeled and may be small; outcomes after an intervention are reported separately and are not used in that subset. No automatic probability recalibration occurs.",
    }


def response_effectiveness_report():
    latest_review = ResponsePlanEffectivenessReview.objects.filter(
        response_plan_id=OuterRef("pk"),
    ).order_by("-reviewed_at", "-created_at").values("pk")[:1]
    completed_plans = ResponsePlan.objects.filter(status="completed").annotate(
        latest_review_id=Subquery(latest_review),
    )
    completed_count = completed_plans.count()
    latest_ids = list(completed_plans.exclude(latest_review_id__isnull=True).values_list("latest_review_id", flat=True))
    reviews = list(ResponsePlanEffectivenessReview.objects.filter(pk__in=latest_ids).select_related(
        "response_plan__assessment_snapshot", "risk_outcome",
    ))
    by_effectiveness = {key: 0 for key, _label in ResponsePlanEffectivenessReview.EFFECTIVENESS}
    for review in reviews:
        by_effectiveness[review.effectiveness] += 1
    actions = ResponseAction.objects.filter(plan__status__in=("approved", "active", "completed"))
    action_counts = {row["status"]: row["total"] for row in actions.values("status").annotate(total=Count("id"))}
    action_total = sum(action_counts.values())
    action_completed = action_counts.get("completed", 0)
    linked_scores = [review.response_plan.assessment_snapshot.risk_score for review in reviews
                     if review.response_plan.assessment_snapshot_id]
    linked_outcomes = {"impact": 0, "no_impact": 0}
    for review in reviews:
        if review.risk_outcome_id:
            linked_outcomes[review.risk_outcome.outcome] += 1
    return {
        "completed_response_plans": completed_count,
        "effectiveness_reviewed_plans": len(reviews),
        "completed_plans_without_review": max(0, completed_count - len(reviews)),
        "latest_review_by_effectiveness": by_effectiveness,
        "action_items_by_status": action_counts,
        "action_items_total": action_total,
        "action_items_completed": action_completed,
        "action_completion_percent": round(action_completed * 100 / action_total, 1) if action_total else None,
        "reviews_linked_to_pre_response_assessment": len(linked_scores),
        "mean_pre_response_risk_score": round(sum(linked_scores) / len(linked_scores), 1) if linked_scores else None,
        "reviews_linked_to_verified_risk_outcome": sum(linked_outcomes.values()),
        "linked_risk_outcomes": linked_outcomes,
        "limitations": "Effectiveness is an approver's evidence-backed assessment, not proof that a plan caused the result. Counts use each completed plan's latest review; action completion is operational tracking, not an effectiveness measure.",
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

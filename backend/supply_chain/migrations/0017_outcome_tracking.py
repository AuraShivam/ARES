import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("supply_chain", "0016_shipment_route_geometry"),
    ]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="delivery_outcome_intervention",
            field=models.CharField(
                choices=[("unknown", "Unknown"), ("none", "No intervention"),
                         ("ares_plan", "ARES response plan applied"),
                         ("external", "External or untracked intervention")],
                default="unknown", max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="shipment",
            name="delivery_outcome_response_plan",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="verified_shipments", to="supply_chain.responseplan",
            ),
        ),
        migrations.AddField(
            model_name="responseplan",
            name="assessment_snapshot",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="response_plans", to="supply_chain.riskassessmentsnapshot",
            ),
        ),
        migrations.AddField(
            model_name="riskoutcome",
            name="assessment_snapshot",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_outcomes", to="supply_chain.riskassessmentsnapshot",
            ),
        ),
        migrations.AddField(
            model_name="riskoutcome",
            name="response_plan",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_risk_outcomes", to="supply_chain.responseplan",
            ),
        ),
        migrations.AddField(
            model_name="riskoutcome",
            name="intervention_status",
            field=models.CharField(
                choices=[("unknown", "Unknown"), ("none", "No intervention"),
                         ("ares_plan", "ARES response plan applied"),
                         ("external", "External or untracked intervention")],
                default="unknown", max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="ResponsePlanEffectivenessReview",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("effectiveness", models.CharField(max_length=24, choices=[
                    ("prevented_impact", "Prevented impact"),
                    ("reduced_impact", "Reduced impact"),
                    ("no_measurable_effect", "No measurable effect"),
                    ("worsened_impact", "Impact worsened"),
                    ("unknown", "Effect unknown"),
                ])),
                ("reviewer", models.CharField(max_length=150)),
                ("evidence_notes", models.TextField()),
                ("action_outcomes", models.JSONField(blank=True, default=list)),
                ("reviewed_at", models.DateTimeField()),
                ("response_plan", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="effectiveness_reviews", to="supply_chain.responseplan",
                )),
                ("risk_outcome", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="effectiveness_reviews", to="supply_chain.riskoutcome",
                )),
            ],
            options={"ordering": ["-reviewed_at", "-created_at"]},
        ),
        migrations.AddIndex(
            model_name="responseplaneffectivenessreview",
            index=models.Index(fields=["response_plan", "reviewed_at"], name="plan_effect_review_idx"),
        ),
        migrations.CreateModel(
            name="ShipmentRiskPredictionSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("prediction_fingerprint", models.CharField(max_length=64)),
                ("shipment_reference", models.CharField(max_length=50)),
                ("purchase_order_number", models.CharField(max_length=40)),
                ("supplier_code", models.CharField(max_length=40)),
                ("supplier_name", models.CharField(max_length=180)),
                ("eta_at_prediction", models.DateField()),
                ("model_version", models.CharField(max_length=120)),
                ("training_cutoff_date", models.DateField()),
                ("late_probability_percent", models.DecimalField(max_digits=5, decimal_places=1)),
                ("model_confidence_percent", models.DecimalField(max_digits=5, decimal_places=1)),
                ("expected_delay_days", models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)),
                ("delay_range_low_days", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("delay_range_high_days", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("feature_snapshot", models.JSONField(blank=True, default=dict)),
                ("factors", models.JSONField(blank=True, default=list)),
                ("material_shortage", models.JSONField(blank=True, default=dict)),
                ("captured_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="ares_shipment_prediction_snapshots", to=settings.AUTH_USER_MODEL,
                )),
                ("shipment", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="risk_prediction_snapshots", to="supply_chain.shipment",
                )),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(fields=("shipment", "prediction_fingerprint"), name="unique_shipment_pred_hash"),
                    models.CheckConstraint(condition=models.Q(late_probability_percent__gte=0, late_probability_percent__lte=100), name="ship_pred_probability_range"),
                    models.CheckConstraint(condition=models.Q(model_confidence_percent__gte=0, model_confidence_percent__lte=100), name="ship_pred_confidence_range"),
                    models.CheckConstraint(condition=models.Q(expected_delay_days__isnull=True) | models.Q(expected_delay_days__gte=0), name="ship_pred_delay_nonnegative"),
                    models.CheckConstraint(condition=(
                        models.Q(delay_range_low_days__isnull=True, delay_range_high_days__isnull=True)
                        | models.Q(delay_range_low_days__isnull=False, delay_range_high_days__isnull=False,
                                   delay_range_high_days__gte=models.F("delay_range_low_days"))
                    ), name="ship_pred_delay_range_valid"),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="shipmentriskpredictionsnapshot",
            index=models.Index(fields=["shipment", "created_at"], name="ship_pred_snap_date_idx"),
        ),
        migrations.AddIndex(
            model_name="shipmentriskpredictionsnapshot",
            index=models.Index(fields=["model_version", "created_at"], name="ship_pred_model_date_idx"),
        ),
    ]

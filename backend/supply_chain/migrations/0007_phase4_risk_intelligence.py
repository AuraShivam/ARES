import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("supply_chain", "0006_external_feed_ingestion")]

    operations = [
        migrations.CreateModel(
            name="RiskAssessmentSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("trigger", models.CharField(choices=[("manual", "Manual request"), ("source_event", "Source event")], default="manual", max_length=20)),
                ("risk_score", models.PositiveSmallIntegerField(validators=[django.core.validators.MaxValueValidator(100)])),
                ("risk_band", models.CharField(max_length=20)),
                ("confidence", models.PositiveSmallIntegerField(validators=[django.core.validators.MaxValueValidator(100)])),
                ("model_version", models.CharField(max_length=120)),
                ("score_breakdown", models.JSONField(blank=True, default=list)),
                ("factors", models.JSONField(blank=True, default=list)),
                ("evidence", models.JSONField(blank=True, default=dict)),
                ("recommendation", models.TextField(blank=True)),
                ("disruption", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="risk_assessments", to="supply_chain.disruption")),
                ("source_event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="risk_assessments", to="supply_chain.externalfeedevent")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RiskAlert",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("active", "Active"), ("cleared", "Cleared")], default="active", max_length=12)),
                ("risk_score", models.PositiveSmallIntegerField(validators=[django.core.validators.MaxValueValidator(100)])),
                ("risk_band", models.CharField(max_length=20)),
                ("threshold_score", models.PositiveSmallIntegerField(validators=[django.core.validators.MaxValueValidator(100)])),
                ("first_triggered_at", models.DateTimeField()),
                ("last_triggered_at", models.DateTimeField()),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("notification_due", models.BooleanField(default=True)),
                ("alert_generation_count", models.PositiveIntegerField(default=1)),
                ("deduplicated_count", models.PositiveIntegerField(default=0)),
                ("cooldown_suppressed_count", models.PositiveIntegerField(default=0)),
                ("disruption", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="risk_alerts", to="supply_chain.disruption")),
                ("latest_assessment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="current_alerts", to="supply_chain.riskassessmentsnapshot")),
            ],
            options={"ordering": ["-last_triggered_at"]},
        ),
        migrations.AddConstraint(
            model_name="riskalert",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "active")), fields=("disruption",), name="unique_active_risk_alert_per_disruption"),
        ),
        migrations.CreateModel(
            name="RiskOutcome",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("outcome", models.CharField(choices=[("impact", "Confirmed supply-chain impact"), ("no_impact", "No material impact")], max_length=12)),
                ("reviewed_by", models.CharField(max_length=150)),
                ("evidence_notes", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField()),
                ("disruption", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="risk_outcome", to="supply_chain.disruption")),
            ],
            options={"ordering": ["-reviewed_at"]},
        ),
    ]

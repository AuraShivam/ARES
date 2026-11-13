import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("supply_chain", "0014_agent_execution_steps"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PredictiveEvaluationRun",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("model_type", models.CharField(choices=[("shipment_delay", "Shipment delay"), ("material_demand", "Material demand")], max_length=24)),
                ("status", models.CharField(choices=[("running", "Running"), ("completed", "Completed"), ("insufficient_data", "Insufficient data"), ("failed", "Failed")], default="running", max_length=20)),
                ("model_version", models.CharField(max_length=120)),
                ("as_of_date", models.DateField()),
                ("holdout_start_date", models.DateField(blank=True, null=True)),
                ("holdout_end_date", models.DateField(blank=True, null=True)),
                ("sample_count", models.PositiveIntegerField(default=0)),
                ("data_fingerprint", models.CharField(blank=True, max_length=64)),
                ("parameters", models.JSONField(blank=True, default=dict)),
                ("metrics", models.JSONField(blank=True, default=dict)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ares_predictive_evaluations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="predictiveevaluationrun",
            index=models.Index(fields=["model_type", "status"], name="pred_eval_type_status_idx"),
        ),
        migrations.AddIndex(
            model_name="predictiveevaluationrun",
            index=models.Index(fields=["created_at"], name="pred_eval_created_idx"),
        ),
    ]

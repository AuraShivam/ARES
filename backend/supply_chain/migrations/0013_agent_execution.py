import uuid

import django.conf
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(django.conf.settings.AUTH_USER_MODEL),
        ("supply_chain", "0012_digital_twin"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentExecution",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("agent_id", models.CharField(choices=[("risk_intelligence", "Risk intelligence"), ("supplier_intelligence", "Supplier intelligence"), ("inventory_intelligence", "Inventory intelligence"), ("logistics_intelligence", "Logistics intelligence"), ("procurement_intelligence", "Procurement intelligence"), ("coordinator", "Coordinator")], max_length=40)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("request_hash", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("running", "Running"), ("succeeded", "Succeeded"), ("partial", "Partial"), ("failed", "Failed")], default="running", max_length=12)),
                ("input_references", models.JSONField(blank=True, default=list)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("provider", models.CharField(blank=True, max_length=40)),
                ("model_name", models.CharField(blank=True, max_length=120)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("tool_call_count", models.PositiveSmallIntegerField(default=0)),
                ("input_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("output_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ares_agent_executions", to=django.conf.settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="agentexecution",
            constraint=models.UniqueConstraint(fields=("requested_by", "idempotency_key"), name="uniq_agent_exec_user_idem"),
        ),
        migrations.AddIndex(
            model_name="agentexecution",
            index=models.Index(fields=["requested_by", "created_at"], name="agent_exec_user_date_idx"),
        ),
        migrations.AddIndex(
            model_name="agentexecution",
            index=models.Index(fields=["agent_id", "status"], name="agent_exec_type_status_idx"),
        ),
    ]

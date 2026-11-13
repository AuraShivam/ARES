import django.db.models.deletion
import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0013_agent_execution")]

    operations = [
        migrations.CreateModel(
            name="AgentExecutionStep",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sequence", models.PositiveSmallIntegerField()),
                ("kind", models.CharField(choices=[("specialist", "Specialist analysis"), ("coordination", "Coordinator synthesis")], max_length=20)),
                ("agent_id", models.CharField(choices=[("risk_intelligence", "Risk intelligence"), ("supplier_intelligence", "Supplier intelligence"), ("inventory_intelligence", "Inventory intelligence"), ("logistics_intelligence", "Logistics intelligence"), ("procurement_intelligence", "Procurement intelligence"), ("coordinator", "Coordinator")], max_length=40)),
                ("status", models.CharField(choices=[("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="running", max_length=12)),
                ("input_references", models.JSONField(blank=True, default=list)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("tool_call_count", models.PositiveSmallIntegerField(default=0)),
                ("input_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("output_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("execution", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="steps", to="supply_chain.agentexecution")),
            ],
            options={"ordering": ["sequence"]},
        ),
        migrations.AddConstraint(
            model_name="agentexecutionstep",
            constraint=models.UniqueConstraint(fields=("execution", "sequence"), name="uniq_agent_step_execution_sequence"),
        ),
        migrations.AddIndex(
            model_name="agentexecutionstep",
            index=models.Index(fields=["execution", "status"], name="agent_step_exec_status_idx"),
        ),
    ]

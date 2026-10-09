import uuid

import django.conf
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(django.conf.settings.AUTH_USER_MODEL),
        ("supply_chain", "0007_phase4_risk_intelligence"),
    ]

    operations = [
        migrations.AddField(
            model_name="responseplan",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ares_response_plans", to=django.conf.settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="responseaction",
            name="action_type",
            field=models.CharField(choices=[("manual", "Manual task"), ("webhook", "Configured webhook")], default="manual", max_length=16),
        ),
        migrations.AddField(
            model_name="responseaction",
            name="execution_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name="ResponseActionExecution",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("adapter", models.CharField(max_length=40)),
                ("mode", models.CharField(choices=[("dry_run", "Dry run"), ("live", "Live")], max_length=12)),
                ("status", models.CharField(choices=[("running", "Running"), ("simulated", "Simulated"), ("succeeded", "Succeeded"), ("failed", "Failed")], max_length=12)),
                ("requested_by", models.CharField(max_length=150)),
                ("approved_by", models.CharField(blank=True, max_length=150)),
                ("result_summary", models.JSONField(blank=True, default=dict)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("started_at", models.DateTimeField()),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("action", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="executions", to="supply_chain.responseaction")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="responseactionexecution",
            index=models.Index(fields=["action", "created_at"], name="action_exec_history_idx"),
        ),
        migrations.AddField(
            model_name="responseactionexecution",
            name="attempt_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.CharField(max_length=64, unique=True)),
                ("notification_type", models.CharField(max_length=80)),
                ("recipient_email", models.EmailField(blank=True, max_length=254)),
                ("subject", models.CharField(max_length=240)),
                ("message", models.TextField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sending", "Sending"), ("retry", "Retry scheduled"), ("sent", "Sent"), ("failed", "Failed"), ("unroutable", "No recipient configured")], default="pending", max_length=16)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80)),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddIndex(
            model_name="notificationdelivery",
            index=models.Index(fields=["status", "next_attempt_at"], name="notification_due_idx"),
        ),
    ]

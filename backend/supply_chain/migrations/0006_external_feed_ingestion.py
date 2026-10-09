import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("supply_chain", "0005_responseplan_reviewer_identity_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dataimport",
            name="entity_type",
            field=models.CharField(choices=[("supplier", "Suppliers"), ("material", "Materials"), ("warehouse", "Warehouses"), ("inventory", "Inventory balances"), ("purchase_order", "Purchase orders"), ("shipment", "Shipments"), ("disruption", "Disruptions")], max_length=30),
        ),
        migrations.AddField(
            model_name="shipment",
            name="source_name",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shipment",
            name="source_key",
            field=models.CharField(blank=True, default="", max_length=160),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shipment",
            name="source_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="disruption",
            name="source_name",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="disruption",
            name="source_key",
            field=models.CharField(blank=True, default="", max_length=160),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="disruption",
            name="source_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="disruption",
            constraint=models.UniqueConstraint(
                condition=~models.Q(source_name="") & ~models.Q(source_key=""),
                fields=("source_name", "source_key"),
                name="unique_disruption_source_key",
            ),
        ),
        migrations.CreateModel(
            name="ExternalFeed",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.SlugField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("enabled", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("syncing", "Syncing"), ("never", "Never synced"), ("ok", "Healthy"), ("partial", "Partial sync"), ("failed", "Failed"), ("disabled", "Not configured")], default="never", max_length=16)),
                ("configuration", models.JSONField(blank=True, default=dict)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("events_seen", models.PositiveIntegerField(default=0)),
                ("events_created", models.PositiveIntegerField(default=0)),
                ("events_updated", models.PositiveIntegerField(default=0)),
                ("events_unchanged", models.PositiveIntegerField(default=0)),
                ("events_ignored", models.PositiveIntegerField(default=0)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="ExternalFeedEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_key", models.CharField(max_length=500)),
                ("event_type", models.CharField(blank=True, max_length=120)),
                ("title", models.CharField(max_length=240)),
                ("severity", models.CharField(blank=True, max_length=20)),
                ("affected_region", models.CharField(blank=True, max_length=240)),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                ("effective_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("lifecycle", models.CharField(choices=[("active", "Active"), ("cancelled", "Cancelled by source"), ("expired", "Expired")], default="active", max_length=16)),
                ("geographies", models.JSONField(blank=True, default=list)),
                ("content_hash", models.CharField(max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("disruption", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="source_events", to="supply_chain.disruption")),
                ("feed", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="supply_chain.externalfeed")),
            ],
            options={"ordering": ["-issued_at", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="externalfeedevent",
            constraint=models.UniqueConstraint(fields=("feed", "source_key"), name="unique_external_feed_event_key"),
        ),
    ]

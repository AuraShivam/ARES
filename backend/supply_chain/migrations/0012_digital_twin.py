import uuid

import django.conf
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(django.conf.settings.AUTH_USER_MODEL),
        ("supply_chain", "0011_shipment_map_coordinates"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplier", name="latitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True,
                                     validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)]),
        ),
        migrations.AddField(
            model_name="supplier", name="longitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True,
                                     validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)]),
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False),
                name="supplier_coordinate_pair",
            ),
        ),
        migrations.AddField(
            model_name="warehouse", name="latitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True,
                                     validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)]),
        ),
        migrations.AddField(
            model_name="warehouse", name="longitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True,
                                     validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)]),
        ),
        migrations.AddConstraint(
            model_name="warehouse",
            constraint=models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False),
                name="warehouse_coordinate_pair",
            ),
        ),
        migrations.AddField(
            model_name="disruption", name="latitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True,
                                     validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)]),
        ),
        migrations.AddField(
            model_name="disruption", name="longitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True,
                                     validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)]),
        ),
        migrations.AddConstraint(
            model_name="disruption",
            constraint=models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False),
                name="disruption_coordinate_pair",
            ),
        ),
        migrations.CreateModel(
            name="DigitalTwinChangeEvent",
            fields=[
                ("sequence", models.BigAutoField(primary_key=True, serialize=False)),
                ("resource", models.CharField(max_length=80)),
                ("entity_id", models.CharField(max_length=80)),
                ("action", models.CharField(max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("delivery_attempts", models.PositiveIntegerField(default=0)),
                ("last_delivery_error", models.CharField(blank=True, max_length=120)),
            ],
            options={"ordering": ["sequence"]},
        ),
        migrations.AddIndex(
            model_name="digitaltwinchangeevent",
            index=models.Index(fields=["published_at", "sequence"], name="twin_change_pending_idx"),
        ),
        migrations.CreateModel(
            name="DigitalTwinSimulation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("scenario", models.JSONField(blank=True, default=dict)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                    related_name="ares_digital_twin_simulations", to=django.conf.settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]

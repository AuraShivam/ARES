from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("supply_chain", "0008_phase5_notifications_and_execution"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorder",
            name="ordered_at",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shipment",
            name="actual_delivery_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shipment",
            name="delivery_outcome_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="shipment",
            name="delivery_outcome_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shipment",
            name="delivery_outcome_verified_by",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="shipment",
            name="delivery_outcome_evidence",
            field=models.TextField(blank=True),
        ),
        migrations.AddIndex(
            model_name="shipment",
            index=models.Index(
                fields=["delivery_outcome_verified", "status", "eta"],
                name="verified_delivery_risk_idx",
            ),
        ),
    ]

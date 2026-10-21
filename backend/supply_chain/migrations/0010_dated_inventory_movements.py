import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("supply_chain", "0009_predictive_delivery_risk"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventorymovement",
            name="purchase_order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="inventory_movements",
                to="supply_chain.purchaseorder",
            ),
        ),
        migrations.AddField(
            model_name="inventorymovement",
            name="occurred_at",
            field=models.DateField(db_index=True, default=django.utils.timezone.localdate),
        ),
        migrations.AddField(
            model_name="inventorymovement",
            name="source_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="inventorymovement",
            name="source_key",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="inventorymovement",
            name="source_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="inventorymovement",
            name="balance_after",
            field=models.DecimalField(blank=True, decimal_places=2, default=None, max_digits=14, null=True),
        ),
        migrations.AddConstraint(
            model_name="inventorymovement",
            constraint=models.UniqueConstraint(
                condition=~Q(source_name="") & ~Q(source_key=""),
                fields=("source_name", "source_key"),
                name="unique_inventory_movement_source_key",
            ),
        ),
    ]

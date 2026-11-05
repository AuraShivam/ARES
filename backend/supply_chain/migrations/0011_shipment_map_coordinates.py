import django.core.validators
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("supply_chain", "0010_dated_inventory_movements"),
    ]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="origin_latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
                validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)],
            ),
        ),
        migrations.AddField(
            model_name="shipment",
            name="origin_longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
                validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)],
            ),
        ),
        migrations.AddField(
            model_name="shipment",
            name="destination_latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
                validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)],
            ),
        ),
        migrations.AddField(
            model_name="shipment",
            name="destination_longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
                validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)],
            ),
        ),
        migrations.AddConstraint(
            model_name="shipment",
            constraint=models.CheckConstraint(
                condition=(
                    Q(origin_latitude__isnull=True, origin_longitude__isnull=True)
                    | Q(origin_latitude__isnull=False, origin_longitude__isnull=False)
                ),
                name="shipment_origin_coord_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="shipment",
            constraint=models.CheckConstraint(
                condition=(
                    Q(destination_latitude__isnull=True, destination_longitude__isnull=True)
                    | Q(destination_latitude__isnull=False, destination_longitude__isnull=False)
                ),
                name="shipment_destination_coord_pair",
            ),
        ),
    ]

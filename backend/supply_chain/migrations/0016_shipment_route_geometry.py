from django.db import migrations, models
import supply_chain.geospatial


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0015_predictive_evaluation_run")]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="route_geometry",
            field=models.JSONField(blank=True, null=True, validators=[supply_chain.geospatial.validate_route_geometry]),
        ),
        migrations.AddField(
            model_name="shipment",
            name="route_geometry_source",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
    ]

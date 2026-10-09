from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("supply_chain", "0004_disruption_response_plans"),
    ]

    operations = [
        migrations.AlterField(
            model_name="responseplan",
            name="reviewed_by",
            field=models.CharField(blank=True, max_length=150),
        ),
    ]

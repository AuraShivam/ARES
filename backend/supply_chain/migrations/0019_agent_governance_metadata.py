from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0018_human_reviewed_workflows")]

    operations = [
        migrations.AddField(
            model_name="agentexecution",
            name="prompt_version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="agentexecution",
            name="policy_version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="agentexecution",
            name="model_version",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="agentexecutionstep",
            name="prompt_version",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]

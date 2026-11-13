from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0017_outcome_tracking")]

    operations = [
        migrations.AddField(
            model_name="agentexecution",
            name="workflow_disruption",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="ares_agent_workflows", to="supply_chain.disruption",
            ),
        ),
        migrations.AddField(
            model_name="agentexecution",
            name="workflow_assessment_snapshot",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="ares_agent_workflows", to="supply_chain.riskassessmentsnapshot",
            ),
        ),
        migrations.AddIndex(
            model_name="agentexecution",
            index=models.Index(fields=["workflow_disruption", "created_at"], name="agent_wf_disrupt_date_idx"),
        ),
        migrations.AddConstraint(
            model_name="agentexecution",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(workflow_disruption__isnull=True, workflow_assessment_snapshot__isnull=True)
                    | models.Q(workflow_disruption__isnull=False, workflow_assessment_snapshot__isnull=False)
                ),
                name="agent_workflow_context_pair",
            ),
        ),
        migrations.AddField(
            model_name="responseplan",
            name="agent_execution",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="response_plans", to="supply_chain.agentexecution",
            ),
        ),
        migrations.AddField(
            model_name="responseplan",
            name="source_recommendation_index",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="responseplan",
            name="agent_recommendation",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="responseplan",
            constraint=models.UniqueConstraint(
                fields=("agent_execution", "source_recommendation_index"),
                name="unique_agent_handoff_selection",
            ),
        ),
        migrations.AddConstraint(
            model_name="responseplan",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(agent_execution__isnull=True, source_recommendation_index__isnull=True)
                    | models.Q(agent_execution__isnull=False, source_recommendation_index__isnull=False)
                ),
                name="response_plan_handoff_pair",
            ),
        ),
    ]

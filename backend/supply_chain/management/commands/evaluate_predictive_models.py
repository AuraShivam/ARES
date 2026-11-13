import json
from datetime import date

from django.core.serializers.json import DjangoJSONEncoder
from django.core.management.base import BaseCommand, CommandError

from supply_chain.predictive_evaluation import run_predictive_evaluation
from supply_chain.serializers import PredictiveEvaluationRunSerializer


class Command(BaseCommand):
    help = "Run and persist a chronological backtest for ARES shipment or demand predictions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            choices=("shipment_delay", "material_demand", "all"),
            default="all",
            help="Which advisory model to evaluate (default: all).",
        )
        parser.add_argument(
            "--as-of-date",
            help="Use a historical business date (YYYY-MM-DD); defaults to today.",
        )

    def handle(self, *args, **options):
        try:
            as_of_date = date.fromisoformat(options["as_of_date"]) if options.get("as_of_date") else None
        except ValueError as exc:
            raise CommandError("--as-of-date must be a valid date in YYYY-MM-DD format.") from exc

        models = ("shipment_delay", "material_demand") if options["model"] == "all" else (options["model"],)
        results = []
        for model_type in models:
            try:
                run = run_predictive_evaluation(model_type, as_of_date=as_of_date)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            results.append(PredictiveEvaluationRunSerializer(run).data)
        self.stdout.write(json.dumps(results, cls=DjangoJSONEncoder, indent=2))

import json

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from supply_chain.risk_workflow import risk_calibration_report


class Command(BaseCommand):
    help = "Summarize risk scores against approver-reviewed disruption outcomes."

    def handle(self, *args, **options):
        try:
            report = risk_calibration_report()
        except ValidationError as exc:
            raise CommandError(f"Risk alert configuration is invalid: {exc}") from exc
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if report["labeled_cases"] == 0:
            self.stderr.write("No reviewed outcomes are recorded yet; calibration cannot be estimated from unlabeled data.")

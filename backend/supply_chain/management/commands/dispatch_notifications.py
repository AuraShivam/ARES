from django.core.management.base import BaseCommand, CommandError

from supply_chain.notifications import dispatch_notifications


class Command(BaseCommand):
    help = "Deliver queued ARES notification emails with retry and idempotency tracking."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="Maximum notifications to attempt (1–1000).")

    def handle(self, *args, **options):
        result = dispatch_notifications(options["limit"])
        if result["status"] == "disabled":
            self.stdout.write("Email delivery is disabled; queued notifications were left unchanged.")
            return
        if result["status"] == "configuration_error":
            raise CommandError(f"Email delivery is enabled but {result['detail']}; queued notifications were left unchanged.")
        self.stdout.write(self.style.SUCCESS(str(result)))

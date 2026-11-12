import time

from django.core.management.base import BaseCommand, CommandError

from supply_chain.models import DigitalTwinChangeEvent
from supply_chain.realtime_signals import _publish_change


class Command(BaseCommand):
    help = "Retry durable ARES digital-twin WebSocket invalidations that were not published."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Repeat until interrupted.")
        parser.add_argument("--interval", type=int, default=10, help="Seconds between retries in watch mode (1–3600).")
        parser.add_argument("--batch-size", type=int, default=100, help="Maximum pending events per pass (1–500).")

    def handle(self, *args, **options):
        interval, batch_size = options["interval"], options["batch_size"]
        if not 1 <= interval <= 3600:
            raise CommandError("--interval must be between 1 and 3600 seconds.")
        if not 1 <= batch_size <= 500:
            raise CommandError("--batch-size must be between 1 and 500.")
        while True:
            pending = list(DigitalTwinChangeEvent.objects.filter(published_at__isnull=True).order_by("sequence")[:batch_size])
            for event in pending:
                _publish_change(event.resource, event.action, sequence=event.sequence, entity_id=event.entity_id)
            if pending:
                self.stdout.write(f"Checked {len(pending)} pending digital-twin event(s).")
            elif not options["watch"]:
                self.stdout.write("No pending digital-twin events.")
            if not options["watch"]:
                return
            time.sleep(interval)

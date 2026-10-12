import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from supply_chain.notifications import dispatch_notifications


logger = logging.getLogger("ares.notifications")


class Command(BaseCommand):
    help = "Continuously dispatch queued ARES notification emails."

    def add_arguments(self, parser):
        parser.add_argument("--interval-seconds", type=int, default=15)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if not settings.ARES_EMAIL_DELIVERY_ENABLED:
            self.stdout.write("Email delivery is disabled; notification worker exited without changing queued rows.")
            return

        interval = max(5, min(options["interval_seconds"], 3600))
        limit = max(1, min(options["limit"], 1000))
        self.stdout.write(f"Notification worker started; polling every {interval} seconds.")
        while True:
            started = time.monotonic()
            try:
                result = dispatch_notifications(limit=limit)
            except Exception as exc:
                logger.error("Notification worker iteration failed", extra={"error_type": type(exc).__name__})
                self.stderr.write(f"Notification worker iteration failed ({type(exc).__name__}).")
            else:
                self.stdout.write(str(result))
            time.sleep(max(1, interval - (time.monotonic() - started)))

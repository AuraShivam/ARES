import time

from django.core.management.base import BaseCommand, CommandError

from supply_chain.gdacs_feed import FeedConfigurationError, feed_configuration, sync_gdacs_alerts


class Command(BaseCommand):
    help = "Poll and normalize global GDACS disaster alerts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Keep polling at the configured interval instead of exiting after one sync.",
        )

    def handle(self, *args, **options):
        try:
            interval = feed_configuration()["poll_interval_seconds"]
        except FeedConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        while True:
            started = time.monotonic()
            try:
                result = sync_gdacs_alerts()
            except FeedConfigurationError as exc:
                raise CommandError(str(exc)) from exc
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"GDACS feed sync failed: {exc}"))
                if not options["watch"]:
                    raise CommandError("GDACS feed sync failed; see the source status endpoint for the recorded error.") from exc
            else:
                self.stdout.write(self.style.SUCCESS(str(result)))

            if not options["watch"]:
                return
            elapsed = time.monotonic() - started
            time.sleep(max(1, interval - elapsed))

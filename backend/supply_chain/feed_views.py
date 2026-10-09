from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .gdacs_feed import FEED_KEY, FEED_NAME, FeedConfigurationError, feed_configuration
from .models import ExternalFeed


@api_view(["GET"])
def feed_status(request):
    configuration_error = ""
    try:
        configuration = feed_configuration()
    except FeedConfigurationError as exc:
        configuration = {"poll_interval_seconds": 360, "minimum_alert_level": "orange"}
        configuration_error = str(exc)

    feed = ExternalFeed.objects.filter(key=FEED_KEY).first()
    config_changed = bool(feed and not configuration_error and feed.configuration != configuration)
    status = "configuration_error" if configuration_error else "configuration_changed" if config_changed else feed.status if feed else "never"
    last_attempt_at = feed.last_attempt_at if feed else None
    elapsed = (timezone.now() - last_attempt_at).total_seconds() if last_attempt_at else None
    recent_events = feed.events.filter(lifecycle="active").count() if feed else 0

    return Response({
        "sources": [{
            "key": FEED_KEY,
            "name": FEED_NAME,
            "provider": "Global Disaster Alert and Coordination System (GDACS)",
            "enabled": not bool(configuration_error),
            "status": status,
            "minimum_alert_level": configuration["minimum_alert_level"],
            "poll_interval_seconds": configuration["poll_interval_seconds"],
            "minimum_poll_interval_seconds": 360,
            "last_attempt_at": last_attempt_at,
            "last_success_at": feed.last_success_at if feed else None,
            "last_error": configuration_error or (feed.last_error if feed else ""),
            "consecutive_failures": feed.consecutive_failures if feed else 0,
            "events_seen": feed.events_seen if feed else 0,
            "events_created": feed.events_created if feed else 0,
            "events_updated": feed.events_updated if feed else 0,
            "events_unchanged": feed.events_unchanged if feed else 0,
            "events_ignored": feed.events_ignored if feed else 0,
            "recent_events": recent_events,
            "duration_ms": feed.duration_ms if feed else 0,
            "next_poll_after_seconds": max(0, int(configuration["poll_interval_seconds"] - elapsed)) if elapsed is not None else 0,
        }],
    })

"""GDACS recent disaster feed polling and normalization for ARES."""

import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone as datetime_timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import AuditEvent, Disruption, ExternalFeed, ExternalFeedEvent
from .risk_workflow import assess_and_record


FEED_KEY = "gdacs-recent-disasters"
FEED_NAME = "GDACS recent disaster alerts"
FEED_SOURCE_NAME = "Global Disaster Alert and Coordination System (GDACS)"
GDACS_FEED_URL = "https://data.gdacs.org/xml/rss_24h.xml"
MIN_POLL_INTERVAL_SECONDS = 360
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
MAX_RETRIES = 3

ALERT_LEVELS = {"green": 1, "orange": 2, "red": 3}
SEVERITY_MAP = {"green": "low", "orange": "high", "red": "critical"}
CONFIDENCE_MAP = {"green": 60, "orange": 80, "red": 90}
EVENT_TYPES = {
    "EQ": "earthquake",
    "TC": "tropical cyclone",
    "FL": "flood",
    "VO": "volcanic activity",
    "WF": "wildfire",
    "FF": "flash flood",
    "DR": "drought",
}


class FeedConfigurationError(ValueError):
    pass


def poll_interval_seconds():
    raw = os.getenv("ARES_GDACS_POLL_INTERVAL_SECONDS", "360")
    try:
        configured = int(raw)
    except (TypeError, ValueError) as exc:
        raise FeedConfigurationError("ARES_GDACS_POLL_INTERVAL_SECONDS must be a whole number of seconds.") from exc
    # GDACS publishes these standard feeds on a six-minute update cycle.
    return max(MIN_POLL_INTERVAL_SECONDS, configured)


def minimum_alert_level():
    value = os.getenv("ARES_GDACS_MIN_ALERT_LEVEL", "orange").strip().casefold()
    if value not in ALERT_LEVELS:
        raise FeedConfigurationError("ARES_GDACS_MIN_ALERT_LEVEL must be green, orange, or red.")
    return value


def feed_configuration():
    return {
        "poll_interval_seconds": poll_interval_seconds(),
        "minimum_alert_level": minimum_alert_level(),
    }


def _user_agent():
    return os.getenv("ARES_GDACS_USER_AGENT", "ARES/1.0 (global-disaster-alert-ingestion)").strip() or "ARES/1.0 (global-disaster-alert-ingestion)"


def _retry_after_seconds(value):
    if not value:
        return None
    try:
        return max(0, min(30, int(value)))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=datetime_timezone.utc)
            return max(0, min(30, int((retry_at - timezone.now()).total_seconds())))
        except (TypeError, ValueError, OverflowError):
            return None


def _fetch_feed_items():
    request = Request(
        GDACS_FEED_URL,
        headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "User-Agent": _user_agent(),
        },
        method="GET",
    )
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            with urlopen(request, timeout=20) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise ValueError("The GDACS response exceeded the 20 MB safety limit.")
            if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", content, flags=re.IGNORECASE):
                raise ValueError("The GDACS feed contained a prohibited document type declaration.")
            root = ET.fromstring(content)
            channel = next((node for node in root.iter() if _local_name(node.tag) == "channel"), None)
            if channel is None:
                raise ValueError("The GDACS response did not contain an RSS channel.")
            items = [node for node in channel if _local_name(node.tag) == "item"]
            if not items:
                raise ValueError("The GDACS response contained no feed items; existing source events were preserved.")
            return items
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == MAX_RETRIES - 1:
                break
            delay = _retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None)
        except (URLError, TimeoutError, OSError, ET.ParseError, UnicodeDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == MAX_RETRIES - 1:
                break
            delay = None
        time.sleep(delay if delay is not None else 2 ** attempt)

    if isinstance(last_error, HTTPError):
        raise RuntimeError(f"GDACS request failed after {MAX_RETRIES} attempts (HTTP {last_error.code}).") from last_error
    name = type(last_error).__name__ if last_error else "unknown error"
    raise RuntimeError(f"GDACS request failed after {MAX_RETRIES} attempts ({name}).") from last_error


def _local_name(tag):
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].split(":")[-1].casefold()


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)


def _plain_text(value):
    value = html.unescape(value or "")
    parser = _TextExtractor()
    parser.feed(value)
    return " ".join(parser.parts).strip() or value.strip()


def _parse_timestamp(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _item_values(item, minimum_level):
    fields = {}
    for child in item:
        name = _local_name(child.tag)
        value = " ".join(part.strip() for part in child.itertext() if part and part.strip())
        if name and value:
            fields[name] = value

    alert_level = (fields.get("alertlevel") or fields.get("alert_level") or "").strip().casefold()
    if alert_level not in ALERT_LEVELS:
        # The level is mandatory for a reliable normalized risk band.
        return None
    if ALERT_LEVELS[alert_level] < ALERT_LEVELS[minimum_level]:
        return {"filtered": True}

    event_type_code = (fields.get("eventtype") or fields.get("event_type") or "").strip().upper()
    event_id = (fields.get("eventid") or fields.get("event_id") or "").strip()
    episode_id = (fields.get("episodeid") or fields.get("episode_id") or "").strip()
    guid = (fields.get("guid") or fields.get("link") or "").strip()
    source_key = ":".join(part for part in ("GDACS", event_type_code, event_id, episode_id) if part) or guid
    if not source_key or len(source_key) > 500:
        return None

    event_type = EVENT_TYPES.get(event_type_code, "natural disaster")
    title = _plain_text(fields.get("eventname") or fields.get("event_name") or fields.get("title") or event_type.title())
    title = title[:180] or "GDACS disaster alert"
    region = _plain_text(fields.get("country") or fields.get("location") or fields.get("where") or "")[:120]
    description = _plain_text(fields.get("description") or "")
    link = fields.get("link") or guid
    issued_at = _parse_timestamp(fields.get("pubdate") or fields.get("datetime") or fields.get("fromdate"))
    effective_at = _parse_timestamp(fields.get("fromdate") or fields.get("startdate"))
    expires_at = _parse_timestamp(fields.get("todate") or fields.get("enddate"))
    geographies = [value for value in (region, fields.get("iso3", "").strip().upper()) if value]
    payload = {
        "source": FEED_SOURCE_NAME,
        "event_type": event_type_code,
        "event_id": event_id,
        "episode_id": episode_id,
        "alert_level": alert_level,
        "title": title,
        "country": region,
        "description": description[:12000],
        "link": link[:1000],
        "pub_date": fields.get("pubdate", ""),
        "from_date": fields.get("fromdate", ""),
        "to_date": fields.get("todate", ""),
        "point": fields.get("point", ""),
        "latitude": fields.get("lat", ""),
        "longitude": fields.get("lon", ""),
        "iso3": fields.get("iso3", ""),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "source_key": source_key,
        "event_type": event_type[:120],
        "title": title,
        "severity_text": alert_level,
        "severity": SEVERITY_MAP[alert_level],
        "confidence": CONFIDENCE_MAP[alert_level],
        "affected_region": region,
        "geographies": geographies,
        "issued_at": issued_at,
        "effective_at": effective_at,
        "expires_at": expires_at,
        "description": description[:12000],
        "payload": payload,
        "content_hash": digest,
    }


def _disruption_snapshot(disruption):
    return {
        "title": disruption.title,
        "disruption_type": disruption.disruption_type,
        "description": disruption.description,
        "affected_region": disruption.affected_region,
        "severity": disruption.severity,
        "confidence": disruption.confidence,
        "status": disruption.status,
        "source_name": disruption.source_name,
        "source_key": disruption.source_key,
        "source_updated_at": disruption.source_updated_at.isoformat() if disruption.source_updated_at else None,
    }


def _upsert_alert(feed, values):
    if values.get("filtered"):
        return "filtered"
    with transaction.atomic():
        # Serialize concurrent pollers so the per-feed/event key remains idempotent.
        ExternalFeed.objects.select_for_update().get(pk=feed.pk)
        event = ExternalFeedEvent.objects.select_for_update().filter(feed=feed, source_key=values["source_key"]).first()
        is_new = event is None
        changed = is_new or event.content_hash != values["content_hash"]
        if not changed:
            if event.lifecycle != "active":
                event.lifecycle = "active"
                event.save(update_fields=["lifecycle", "updated_at"])
                if event.disruption_id:
                    assess_and_record(event.disruption, trigger="source_event", source_event=event)
                return "updated"
            return "unchanged"

        description = f"Source: {FEED_SOURCE_NAME}.\n\n{values['description']}".strip()
        disruption = event.disruption if event else None
        before = _disruption_snapshot(disruption) if disruption else None
        if disruption is None:
            disruption = Disruption(
                title=values["title"],
                disruption_type=values["event_type"],
                description=description,
                affected_region=values["affected_region"],
                severity=values["severity"],
                confidence=values["confidence"],
                source_name=FEED_SOURCE_NAME,
                source_key=values["source_key"][:160],
                source_updated_at=values["issued_at"] or values["effective_at"],
            )
            disruption.save()
            action = "create"
            previous = None
        else:
            disruption.title = values["title"]
            disruption.disruption_type = values["event_type"]
            disruption.description = description
            disruption.affected_region = values["affected_region"]
            disruption.severity = values["severity"]
            disruption.confidence = values["confidence"]
            disruption.source_name = FEED_SOURCE_NAME
            disruption.source_key = values["source_key"][:160]
            disruption.source_updated_at = values["issued_at"] or values["effective_at"]
            disruption.save(update_fields=[
                "title", "disruption_type", "description", "affected_region", "severity",
                "confidence", "source_name", "source_key", "source_updated_at", "updated_at",
            ])
            action = "update"
            previous = before
        AuditEvent.objects.create(
            entity_type="supply_chain.disruption",
            entity_id=str(disruption.pk),
            action=action,
            actor="gdacs-feed",
            changes={"before": previous, "after": _disruption_snapshot(disruption), "source_event": values["source_key"]},
        )

        defaults = {
            "event_type": values["event_type"],
            "title": values["title"][:240],
            "severity": values["severity_text"],
            "affected_region": values["affected_region"][:240],
            "geographies": values["geographies"],
            "issued_at": values["issued_at"],
            "effective_at": values["effective_at"],
            "expires_at": values["expires_at"],
            "lifecycle": "active",
            "content_hash": values["content_hash"],
            "payload": values["payload"],
            "disruption": disruption,
        }
        if event is None:
            event = ExternalFeedEvent.objects.create(feed=feed, source_key=values["source_key"], **defaults)
        else:
            for field, value in defaults.items():
                setattr(event, field, value)
            event.save(update_fields=[*defaults.keys(), "updated_at"])
        assess_and_record(disruption, trigger="source_event", source_event=event)
    return "created" if is_new else "updated"


def sync_gdacs_alerts():
    """Poll the global GDACS recent-events RSS feed and upsert significant alerts."""
    configuration = feed_configuration()
    now = timezone.now()
    with transaction.atomic():
        feed, _created = ExternalFeed.objects.get_or_create(
            key=FEED_KEY,
            defaults={"name": FEED_NAME, "enabled": True, "configuration": configuration},
        )
        feed = ExternalFeed.objects.select_for_update().get(pk=feed.pk)
        feed.name = FEED_NAME
        feed.enabled = True
        if feed.last_attempt_at and now - feed.last_attempt_at < timedelta(seconds=configuration["poll_interval_seconds"]):
            return {
                "status": "skipped",
                "message": "The feed was polled recently; the configured minimum interval has not elapsed.",
                "last_success_at": feed.last_success_at,
            }
        feed.configuration = configuration
        feed.status = "syncing"
        feed.last_attempt_at = now
        feed.last_error = ""
        feed.events_seen = 0
        feed.events_created = 0
        feed.events_updated = 0
        feed.events_unchanged = 0
        feed.events_ignored = 0
        feed.save(update_fields=[
            "name", "enabled", "configuration", "status", "last_attempt_at", "last_error",
            "events_seen", "events_created", "events_updated", "events_unchanged", "events_ignored", "updated_at",
        ])

    started = time.monotonic()
    try:
        items = _fetch_feed_items()
        counts = {"created": 0, "updated": 0, "unchanged": 0, "ignored": 0}
        seen_keys = set()
        for item in items:
            values = _item_values(item, configuration["minimum_alert_level"])
            if values is None:
                counts["ignored"] += 1
                continue
            if values.get("filtered"):
                continue
            seen_keys.add(values["source_key"])
            action = _upsert_alert(feed, values)
            if action in counts:
                counts[action] += 1

        # GDACS's selected standard feed is a rolling 24-hour window. Mark records
        # no longer listed as aged out only when every feed item parsed successfully.
        # This only changes source-event history; it never resolves an ARES disruption.
        with transaction.atomic():
            ExternalFeed.objects.select_for_update().get(pk=feed.pk)
            ignored = counts["ignored"]
            if not ignored:
                old_events = ExternalFeedEvent.objects.filter(feed=feed, lifecycle="active")
                for event in old_events.iterator():
                    if event.source_key not in seen_keys:
                        event.lifecycle = "expired"
                        event.save(update_fields=["lifecycle", "updated_at"])
            feed.status = "partial" if ignored else "ok"
            feed.last_error = f"{ignored} malformed feed item(s) were skipped." if ignored else ""
            feed.last_success_at = timezone.now()
            feed.consecutive_failures = 0
            feed.events_seen = len(seen_keys)
            feed.events_created = counts["created"]
            feed.events_updated = counts["updated"]
            feed.events_unchanged = counts["unchanged"]
            feed.events_ignored = ignored
            feed.duration_ms = max(0, int((time.monotonic() - started) * 1000))
            feed.save(update_fields=[
                "status", "last_error", "last_success_at", "consecutive_failures", "events_seen",
                "events_created", "events_updated", "events_unchanged", "events_ignored",
                "duration_ms", "updated_at",
            ])
        return {"status": feed.status, "counts": counts}
    except Exception as exc:
        with transaction.atomic():
            feed = ExternalFeed.objects.select_for_update().get(pk=feed.pk)
            feed.status = "failed"
            feed.last_error = str(exc)[:500]
            feed.consecutive_failures += 1
            feed.duration_ms = max(0, int((time.monotonic() - started) * 1000))
            feed.save(update_fields=["status", "last_error", "consecutive_failures", "duration_ms", "updated_at"])
        raise

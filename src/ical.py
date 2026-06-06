from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from urllib.parse import urlencode
from uuid import uuid4
from zoneinfo import ZoneInfo

from schemas import USTimeZone


def _escape(text: str) -> str:
    # RFC 5545 text values must escape backslash, comma, semicolon, and newlines.
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    # RFC 5545 content lines should not exceed 75 octets; continuations start
    # with a single space.
    if len(line) <= 75:
        return line
    chunks = [line[:75]]
    rest = line[75:]
    while rest:
        chunks.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(chunks)


def _time_lines(
    event_date: date,
    event_time: time | None,
    timezone: USTimeZone | None,
    duration_minutes: int,
) -> list[str]:
    if event_time is None:
        # All-day event; DTEND date is exclusive.
        start = event_date.strftime("%Y%m%d")
        end = (event_date + timedelta(days=1)).strftime("%Y%m%d")
        return [f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}"]

    start_naive = datetime.combine(event_date, event_time)
    end_naive = start_naive + timedelta(minutes=duration_minutes)

    if timezone is not None:
        # Convert to UTC so the absolute time is unambiguous everywhere.
        tz = ZoneInfo(timezone.value)
        start = start_naive.replace(tzinfo=tz).astimezone(dt_timezone.utc)
        end = end_naive.replace(tzinfo=tz).astimezone(dt_timezone.utc)
        return [
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        ]

    # No timezone -> floating local time, interpreted in the viewer's own zone.
    return [
        f"DTSTART:{start_naive.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{end_naive.strftime('%Y%m%dT%H%M%S')}",
    ]


def build_ics(
    *,
    title: str,
    event_date: date,
    event_time: time | None,
    timezone: USTimeZone | None,
    location: str,
    description: str,
    duration_minutes: int,
) -> str:
    """Build an RFC 5545 .ics document for a single hearing event."""
    dtstamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LawyerAI//Hearing//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uuid4()}@lawyerai",
        f"DTSTAMP:{dtstamp}",
        *_time_lines(event_date, event_time, timezone, duration_minutes),
        f"SUMMARY:{_escape(title or 'Hearing')}",
    ]
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]

    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _start_end(
    event_date: date,
    event_time: time | None,
    timezone: USTimeZone | None,
    duration_minutes: int,
) -> tuple[date | datetime, date | datetime, bool]:
    """Return (start, end, all_day). Timed events with a known zone are UTC-aware
    datetimes; without a zone they are naive (floating local); all-day are dates."""
    if event_time is None:
        return event_date, event_date + timedelta(days=1), True

    start = datetime.combine(event_date, event_time)
    end = start + timedelta(minutes=duration_minutes)
    if timezone is not None:
        tz = ZoneInfo(timezone.value)
        start = start.replace(tzinfo=tz).astimezone(dt_timezone.utc)
        end = end.replace(tzinfo=tz).astimezone(dt_timezone.utc)
    return start, end, False


def google_calendar_url(
    *,
    title: str,
    event_date: date,
    event_time: time | None,
    timezone: USTimeZone | None,
    location: str,
    description: str,
    duration_minutes: int,
) -> str:
    """One-click 'Add to Google Calendar' link with the event pre-filled."""
    start, end, all_day = _start_end(event_date, event_time, timezone, duration_minutes)
    if all_day:
        dates = f"{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}"
    elif start.tzinfo is not None:
        dates = f"{start.strftime('%Y%m%dT%H%M%SZ')}/{end.strftime('%Y%m%dT%H%M%SZ')}"
    else:
        dates = f"{start.strftime('%Y%m%dT%H%M%S')}/{end.strftime('%Y%m%dT%H%M%S')}"

    params = {"action": "TEMPLATE", "text": title or "Hearing", "dates": dates}
    if location:
        params["location"] = location
    if description:
        params["details"] = description
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def outlook_url(
    *,
    title: str,
    event_date: date,
    event_time: time | None,
    timezone: USTimeZone | None,
    location: str,
    description: str,
    duration_minutes: int,
) -> str:
    """One-click 'Add to Outlook' link with the event pre-filled."""
    start, end, all_day = _start_end(event_date, event_time, timezone, duration_minutes)
    params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": title or "Hearing",
    }
    if all_day:
        params["allday"] = "true"
        params["startdt"] = start.strftime("%Y-%m-%d")
        params["enddt"] = end.strftime("%Y-%m-%d")
    elif start.tzinfo is not None:
        params["startdt"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["enddt"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        params["startdt"] = start.strftime("%Y-%m-%dT%H:%M:%S")
        params["enddt"] = end.strftime("%Y-%m-%dT%H:%M:%S")

    if location:
        params["location"] = location
    if description:
        params["body"] = description
    return "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(params)

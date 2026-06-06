from datetime import date, time
from enum import Enum
from zoneinfo import ZoneInfo

from pydantic import BaseModel


class Meridiem(str, Enum):
    am = "AM"
    pm = "PM"


class USTimeZone(str, Enum):
    pacific = "America/Los_Angeles"
    mountain = "America/Denver"
    central = "America/Chicago"
    eastern = "America/New_York"
    alaska = "America/Anchorage"
    hawaii = "Pacific/Honolulu"
    arizona = "America/Phoenix"


_TZ_ABBREV = {
    USTimeZone.pacific: "PT",
    USTimeZone.mountain: "MT",
    USTimeZone.central: "CT",
    USTimeZone.eastern: "ET",
    USTimeZone.alaska: "AKT",
    USTimeZone.hawaii: "HT",
    USTimeZone.arizona: "MST",
}

# Friendly labels for timezone pickers.
TZ_LABELS = {
    USTimeZone.pacific: "Pacific (PT)",
    USTimeZone.mountain: "Mountain (MT)",
    USTimeZone.central: "Central (CT)",
    USTimeZone.eastern: "Eastern (ET)",
    USTimeZone.alaska: "Alaska (AKT)",
    USTimeZone.hawaii: "Hawaii (HT)",
    USTimeZone.arizona: "Arizona (MST)",
}

# Best-effort state -> timezone map for inferring a default when a filing does
# not state one. Convenience only; the user can always override.
_STATE_TIMEZONES = {
    USTimeZone.pacific: ("california", "washington", "oregon", "nevada"),
    USTimeZone.arizona: ("arizona",),
    USTimeZone.mountain: (
        "colorado", "utah", "montana", "idaho", "wyoming", "new mexico",
    ),
    USTimeZone.central: (
        "texas", "illinois", "missouri", "louisiana", "minnesota", "wisconsin",
        "iowa", "oklahoma", "arkansas", "kansas", "nebraska", "tennessee",
        "alabama", "mississippi", "north dakota", "south dakota",
    ),
    USTimeZone.eastern: (
        "new york", "florida", "georgia", "virginia", "massachusetts",
        "pennsylvania", "new jersey", "michigan", "ohio", "north carolina",
        "south carolina", "connecticut", "maryland", "maine", "indiana",
        "kentucky", "district of columbia", "new hampshire", "vermont",
        "rhode island", "delaware", "west virginia",
    ),
    USTimeZone.alaska: ("alaska",),
    USTimeZone.hawaii: ("hawaii",),
}


def infer_timezone(court_name: str | None) -> USTimeZone | None:
    """Guess a timezone from a court name (e.g. "...District of California")."""
    if not court_name:
        return None
    text = court_name.lower()
    for zone, states in _STATE_TIMEZONES.items():
        if any(state in text for state in states):
            return zone
    return None


class HearingDate(BaseModel):
    """Hearing date as numeric components, composed into a real date on demand."""

    year: int | None = None
    month: int | None = None
    day: int | None = None

    def to_date(self) -> date | None:
        if self.year and self.month and self.day:
            try:
                return date(self.year, self.month, self.day)
            except ValueError:
                return None
        return None

    def display(self) -> str | None:
        composed = self.to_date()
        return composed.isoformat() if composed else None


class HearingTime(BaseModel):
    """Hearing time as 12-hour components plus an IANA timezone."""

    hour: int | None = None  # 1-12 as written on a 12-hour clock
    minute: int | None = None  # 0-59
    meridiem: Meridiem | None = None
    timezone: USTimeZone | None = None

    def to_time(self) -> time | None:
        if self.hour is None or self.meridiem is None:
            return None
        hour24 = self.hour % 12
        if self.meridiem is Meridiem.pm:
            hour24 += 12
        try:
            return time(hour24, self.minute or 0)
        except ValueError:
            return None

    def tzinfo(self) -> ZoneInfo | None:
        return ZoneInfo(self.timezone.value) if self.timezone else None

    def display(self) -> str | None:
        composed = self.to_time()
        if composed is None:
            return None
        hour12 = composed.hour % 12 or 12
        label = f"{hour12}:{composed.minute:02d} {self.meridiem.value}"
        if self.timezone:
            label += f" {_TZ_ABBREV[self.timezone]}"
        return label


class HearingLocation(BaseModel):
    """Hearing location split into courtroom designation and street address."""

    department: str | None = None  # e.g. "Dept. 17"
    address: str | None = None  # street, city, state, ZIP on one line

    def display(self) -> str | None:
        parts = [part for part in (self.department, self.address) if part]
        return ", ".join(parts) if parts else None


class DocumentAnalysis(BaseModel):
    case_name: str | None = None
    case_number: str | None = None
    court_name: str | None = None
    hearing_date: HearingDate | None = None
    hearing_time: HearingTime | None = None
    hearing_location: HearingLocation | None = None
    motion_name: str | None = None
    motion_summary: str | None = None

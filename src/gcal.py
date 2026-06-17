"""Per-client Google Calendar sync.

Each client connects their own Google account once (OAuth), after which the
app writes hearing events straight into their primary calendar via the
Calendar API. Tokens live in the Streamlit session only (no server-side
storage), so a client re-connects each new session — acceptable while the
OAuth app is in Google's "Testing" status anyway.
"""

import os

# Google often echoes back a slightly different scope set than requested;
# relax oauthlib so fetch_token doesn't raise on that.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import streamlit as st
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from schemas import DocumentAnalysis, infer_timezone

# Manage events only — narrower than full calendar access, and easier to get
# verified by Google.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_CREDS_KEY = "google_creds"


def _conf() -> dict:
    return st.secrets["google_oauth"]


def _build_flow() -> Flow:
    conf = _conf()
    redirect_uri = conf["redirect_uri"]

    # localhost runs over http; oauthlib refuses insecure transport unless told
    # to allow it. Deployed app uses https, so this only relaxes for local dev.
    if redirect_uri.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    client_config = {
        "web": {
            "client_id": conf["client_id"],
            "client_secret": conf["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    # Disable PKCE: we build a fresh Flow on the redirect, so the code_verifier
    # generated when the consent URL was created is gone by token-exchange time
    # (it would fail with "Missing code verifier"). The client_secret already
    # secures this server-side web flow.
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES, autogenerate_code_verifier=False
    )
    flow.redirect_uri = redirect_uri
    return flow


def auth_url() -> str:
    """Google consent URL. access_type=offline + prompt=consent so we receive a
    refresh token the first time."""
    flow = _build_flow()
    url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url


def _creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def _credentials() -> Credentials | None:
    data = st.session_state.get(_CREDS_KEY)
    return Credentials(**data) if data else None


def is_connected() -> bool:
    return _CREDS_KEY in st.session_state


def disconnect() -> None:
    """Forget the session's Google credentials so the client can reconnect
    (e.g. to switch accounts)."""
    st.session_state.pop(_CREDS_KEY, None)


_ERROR_KEY = "google_auth_error"


def last_error() -> str | None:
    return st.session_state.get(_ERROR_KEY)


def handle_redirect() -> None:
    """Catch Google's redirect back to the app (`?code=...`), exchange it for
    credentials, and stash them in the session. Call once at the top of every
    run, before building the UI."""
    if is_connected():
        return

    # Google reports consent failures (e.g. access_denied) as ?error=...
    if "error" in st.query_params:
        st.session_state[_ERROR_KEY] = st.query_params.get("error")
        st.query_params.clear()
        return

    code = st.query_params.get("code")
    if not code:
        return

    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as error:
        # Surface the reason rather than silently staying "Not connected".
        st.session_state[_ERROR_KEY] = str(error)
        st.query_params.clear()
        return

    st.session_state.pop(_ERROR_KEY, None)
    st.session_state[_CREDS_KEY] = _creds_to_dict(flow.credentials)
    st.query_params.clear()


def _event_body(analysis: DocumentAnalysis, duration_minutes: int) -> dict:
    event_date = analysis.hearing_date.to_date() if analysis.hearing_date else None
    if event_date is None:
        raise ValueError("No clear hearing date was extracted from the filing.")

    event_time = analysis.hearing_time.to_time() if analysis.hearing_time else None
    timezone = (
        analysis.hearing_time.timezone if analysis.hearing_time else None
    ) or infer_timezone(analysis.court_name)

    title = analysis.motion_name or analysis.case_name or "Hearing"
    if analysis.case_number:
        title = f"{title} (Case No. {analysis.case_number})"
    body: dict = {"summary": title}

    location = (
        analysis.hearing_location.display() if analysis.hearing_location else None
    )
    if location:
        body["location"] = location

    # Paper trail: a wrong AI extraction lands silently in a legal calendar, so
    # flag the source and keep the case number and the model's summary alongside it.
    note = "⚠️ Auto-extracted from an uploaded filing — verify against the document."
    case_line = f"Case No. {analysis.case_number}" if analysis.case_number else None
    summary = analysis.motion_summary
    parts = [note, case_line, summary]
    body["description"] = "\n\n".join(part for part in parts if part)

    if event_time is None:
        # All-day event; the Calendar API treats the end date as exclusive.
        body["start"] = {"date": event_date.isoformat()}
        body["end"] = {"date": (event_date + timedelta(days=1)).isoformat()}
    else:
        start = datetime.combine(event_date, event_time)
        end = start + timedelta(minutes=duration_minutes)
        body["start"] = {"dateTime": start.isoformat()}
        body["end"] = {"dateTime": end.isoformat()}
        if timezone is not None:
            body["start"]["timeZone"] = timezone.value
            body["end"]["timeZone"] = timezone.value
        # else: no zone -> Google interprets the naive time in the calendar's
        # own default timezone.

    return body


def insert_event(analysis: DocumentAnalysis, duration_minutes: int) -> str | None:
    """Create the hearing on the connected client's primary calendar and return
    a link to the created event."""
    creds = _credentials()
    if creds is None:
        raise RuntimeError("Not connected to Google Calendar.")

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    body = _event_body(analysis, duration_minutes)
    created = service.events().insert(calendarId="primary", body=body).execute()

    # Persist any token the client library refreshed mid-call.
    st.session_state[_CREDS_KEY] = _creds_to_dict(creds)
    return created.get("htmlLink")

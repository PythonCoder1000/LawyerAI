import hmac
import streamlit as st
import pandas as pd
from llm import analyze
from config import MODELS
from schemas import USTimeZone, TZ_LABELS, infer_timezone
from ical import google_calendar_url, outlook_url


def password_entered():
    expected = st.secrets.get("APP_PASSWORD")
    if expected and hmac.compare_digest(st.session_state["password"], expected):
        st.session_state["password_correct"] = True

    else:
        st.session_state["password_correct"] = False

    del st.session_state["password"]


def check_password():
    if st.session_state.get("password_correct", False):
        return True

    st.text_input(
        "Password", type="password", on_change=password_entered, key="password"
    )

    return False


if not check_password():
    st.stop()

st.title("Lawyer PDF Analyzer")

with st.sidebar:
    st.subheader("Settings")
    labels = [model["label"] for model in MODELS]
    captions = [model["caption"] for model in MODELS]

    choice = st.radio("Model", labels, captions=captions, index=0)
    selected_model = next(model for model in MODELS if model["label"] == choice)

    st.divider()
    st.markdown("**Calendar**")

    if "event_duration" not in st.session_state:
        st.session_state["event_duration"] = 60

    st.number_input(
        "Default event length (minutes)",
        min_value=15,
        max_value=480,
        step=15,
        key="event_duration",
        help="Hearings rarely state an end time; this sets the event length.",
    )

uploaded = st.file_uploader("Upload a PDF", type="pdf")

if uploaded:
    # Drop a previous analysis when a different file is uploaded, so the results
    # and calendar form never describe a hearing from the prior PDF.
    if st.session_state.get("result_sig") != uploaded.file_id:
        st.session_state.pop("result", None)
        st.session_state["result_sig"] = uploaded.file_id

    if st.button("Analyze PDF", type="primary"):
        with st.spinner("Analyzing the filing..."):
            try:
                result = analyze(uploaded.getvalue(), selected_model)
            except Exception as error:
                st.error(f"Couldn't analyze the PDF: {error}")
                st.stop()

        st.session_state["result"] = result

    if "result" in st.session_state:
        result = st.session_state["result"]

        if result is None:
            st.write("Error: the model returned no result. Please try again.")

        else:
            hearing_date = result.hearing_date.display() if result.hearing_date else None
            hearing_time = result.hearing_time.display() if result.hearing_time else None
            hearing_location = (
                result.hearing_location.display() if result.hearing_location else None
            )

            df = pd.DataFrame(
                [
                    ("Case Name", result.case_name),
                    ("Case Number", result.case_number),
                    ("Court", result.court_name),
                    ("Hearing Date", hearing_date),
                    ("Hearing Time", hearing_time),
                    ("Hearing Location", hearing_location),
                    ("Motion", result.motion_name),
                    ("Summary", result.motion_summary),
                ],
                columns=["Field", "Value"],
            )
            st.dataframe(df, hide_index=True, use_container_width=True)

            st.subheader("Add to Calendar")
            st.caption(
                "Review and fill in anything missing or incorrect, then download "
                "the event and open it in Google, Apple, or Outlook calendar."
            )

            title = st.text_input(
                "Title", value=result.motion_name or result.case_name or ""
            )

            event_date = st.date_input(
                "Date",
                value=result.hearing_date.to_date() if result.hearing_date else None,
            )

            event_time = st.time_input(
                "Time",
                value=result.hearing_time.to_time() if result.hearing_time else None,
            )

            # None = floating local time, interpreted in the viewer's own zone,
            # rather than forcing one when the filing states no timezone.
            tz_options = [None, *USTimeZone]
            extracted_tz = result.hearing_time.timezone if result.hearing_time else None
            default_tz = extracted_tz or infer_timezone(result.court_name)
            tz_index = tz_options.index(default_tz) if default_tz in tz_options else 0
            event_tz = st.selectbox(
                "Timezone",
                tz_options,
                index=tz_index,
                format_func=lambda zone: (
                    "Local time" if zone is None else TZ_LABELS[zone]
                ),
            )

            event_location = st.text_input(
                "Location",
                value=(
                    result.hearing_location.display()
                    if result.hearing_location
                    else ""
                ),
            )

            event_description = st.text_area(
                "Description", value=result.motion_summary or ""
            )

            ready = bool(title) and event_date is not None
            if ready:
                event = {
                    "title": title,
                    "event_date": event_date,
                    "event_time": event_time,
                    "timezone": event_tz,
                    "location": event_location,
                    "description": event_description,
                    "duration_minutes": int(st.session_state["event_duration"]),
                }
                gcal_link = google_calendar_url(**event)
                outlook_link = outlook_url(**event)
            else:
                gcal_link = "https://calendar.google.com"
                outlook_link = "https://outlook.live.com"

            st.caption("Add it to your calendar:")
            google_col, outlook_col = st.columns(2)
            with google_col:
                st.link_button(
                    "Google Calendar",
                    gcal_link,
                    type="primary",
                    disabled=not ready,
                    use_container_width=True,
                )
            with outlook_col:
                st.link_button(
                    "Outlook",
                    outlook_link,
                    disabled=not ready,
                    use_container_width=True,
                )
            if not ready:
                st.caption("Add a title and date to enable these.")

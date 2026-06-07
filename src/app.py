import streamlit as st
import pandas as pd
from llm import analyze
from config import MODELS
import gcal

st.set_page_config(
    page_title="Lawyer PDF Analyzer",
    page_icon="⚖️",
    layout="centered",
)

# Catch Google's OAuth redirect (?code=...) before drawing anything else.
gcal.handle_redirect()

# Style the OAuth link to match a primary button. A plain anchor (not a
# button + JS) is used so the consent page opens in this same tab and returns
# here, sidestepping Streamlit's sandboxed component iframe.
st.markdown(
    """
    <style>
    a.gcal-connect-btn {
        display: block;
        width: 100%;
        box-sizing: border-box;
        text-align: center;
        padding: 0.5rem 0.75rem;
        background-color: #ff4b4b;
        color: #ffffff !important;
        border-radius: 0.5rem;
        text-decoration: none;
        font-weight: 600;
    }
    a.gcal-connect-btn:hover { background-color: #ff6c6c; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "event_duration" not in st.session_state:
    st.session_state["event_duration"] = 60


# --- Sidebar -----------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    labels = [model["label"] for model in MODELS]
    captions = [model["caption"] for model in MODELS]
    choice = st.radio("Model", labels, captions=captions, index=0)
    selected_model = next(model for model in MODELS if model["label"] == choice)

    st.number_input(
        "Default event length (minutes)",
        min_value=15,
        max_value=480,
        step=15,
        key="event_duration",
        help="Hearings rarely state an end time; this sets the event length.",
    )

    st.divider()
    st.subheader("Google Calendar")
    with st.container(border=True):
        if gcal.is_connected():
            st.success("Connected", icon="✅")
            st.caption("Analyzed hearings sync to your calendar automatically.")
            if st.button("Disconnect", width="stretch"):
                gcal.disconnect()
                st.rerun()
        else:
            st.warning("Not connected", icon="🔌")
            # Open Google's consent page in a new tab. On Streamlit Cloud the
            # app runs in a sandboxed iframe: "_self" loads OAuth inside the
            # frame (Google blocks it with a 403) and "_top" is silently
            # blocked by the sandbox, so neither navigates. "_blank" escapes to
            # a top-level tab where OAuth works; after approval Google redirects
            # that tab to the app and handle_redirect() completes the connection.
            st.markdown(
                f'<a class="gcal-connect-btn" target="_blank" rel="noopener" '
                f'href="{gcal.auth_url()}">Connect Google Calendar</a>',
                unsafe_allow_html=True,
            )
            st.caption(
                "Connect once, then every analyzed filing is added to your "
                "calendar automatically."
            )


# --- Main --------------------------------------------------------------------
st.title("⚖️ Lawyer PDF Analyzer")
st.caption(
    "Upload a legal filing, click **Analyze**, and the hearing is added "
    "straight to your Google Calendar."
)

if gcal.is_connected():
    st.success("Google Calendar connected — hearings sync automatically.", icon="✅")
else:
    error = gcal.last_error()
    if error:
        st.error(f"Google Calendar connection failed: {error}", icon="🚫")
    st.info(
        "Connect Google Calendar in the sidebar to auto-sync hearings.",
        icon="🔌",
    )

uploaded = st.file_uploader("Upload a PDF", type="pdf")

if uploaded:
    # Drop a previous analysis when a different file is uploaded, so the results
    # and sync status never describe a hearing from the prior PDF.
    if st.session_state.get("result_sig") != uploaded.file_id:
        st.session_state.pop("result", None)
        st.session_state.pop("synced_link", None)
        st.session_state.pop("synced_sig", None)
        st.session_state["result_sig"] = uploaded.file_id

    if st.button("Analyze PDF", type="primary", width="stretch"):
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
            st.error("The model returned no result. Please try analyzing again.")

        else:
            hearing_date = result.hearing_date.display() if result.hearing_date else None
            hearing_time = result.hearing_time.display() if result.hearing_time else None
            hearing_location = (
                result.hearing_location.display() if result.hearing_location else None
            )

            st.subheader("Extracted details")
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
            st.dataframe(df, hide_index=True, width="stretch")

            # Auto-sync into the connected client's Google Calendar.
            has_date = bool(result.hearing_date and result.hearing_date.to_date())

            if not gcal.is_connected():
                st.info(
                    "Connect Google Calendar in the sidebar to automatically "
                    "add this hearing to your calendar.",
                    icon="🔌",
                )
            elif not has_date:
                st.warning(
                    "No clear hearing date was found, so nothing was added to "
                    "your calendar.",
                    icon="⚠️",
                )
            else:
                # Insert exactly once per uploaded file; reruns just show status.
                if st.session_state.get("synced_sig") != uploaded.file_id:
                    with st.spinner("Adding to your Google Calendar..."):
                        try:
                            link = gcal.insert_event(
                                result, int(st.session_state["event_duration"])
                            )
                        except Exception as error:
                            st.error(f"Couldn't add to Google Calendar: {error}")
                        else:
                            st.session_state["synced_sig"] = uploaded.file_id
                            st.session_state["synced_link"] = link

                if st.session_state.get("synced_sig") == uploaded.file_id:
                    st.success("Added to your Google Calendar.", icon="✅")
                    link = st.session_state.get("synced_link")
                    if link:
                        st.link_button("View event", link)

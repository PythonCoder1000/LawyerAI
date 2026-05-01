import hmac
import streamlit as st
import pandas as pd
from llm import analyze
from pdf import extract_text
from config import MODELS


def password_entered():
    if hmac.compare_digest(st.session_state["password"], st.secrets["APP_PASSWORD"]):
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

uploaded = st.file_uploader("Upload a PDF", type="pdf")

if uploaded:
    text = extract_text(uploaded)

    if st.button("Analyze PDF", type="primary"):
        with st.spinner("Thinking..."):
            result = analyze(
                text, selected_model["id"], selected_model["reasoning_effort"]
            )

        st.session_state["result"] = result

    if "result" in st.session_state:
        result = st.session_state["result"]

        if result is None:
            st.write("Error: OPENAI API Response was NONE! Please try again.")

        else:
            df = pd.DataFrame(
                [
                    ("Case Name", result.case_name),
                    ("Case Number", result.case_number),
                    ("Court", result.court_name),
                    ("Hearing Date", result.hearing_date),
                    ("Hearing Time", result.hearing_time),
                    ("Hearing Location", result.hearing_location),
                    ("Motion", result.motion_name),
                    ("Summary", result.motion_summary),
                ],
                columns=["Field", "Value"],
            )
            st.dataframe(df, hide_index=True, use_container_width=True)

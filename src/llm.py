import streamlit as st
from openai import OpenAI
from config import OPENAI_API_KEY, EXTRACT_LLM_PROMPT
from schemas import DocumentAnalysis

client = OpenAI(api_key=OPENAI_API_KEY)


@st.cache_data(show_spinner=False)
def analyze(text: list[dict], model: str, reasoning_effort: str) -> DocumentAnalysis:
    if reasoning_effort is None:
        response = client.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACT_LLM_PROMPT},
                {"role": "user", "content": f"Document:\n{text}"},
            ],
            response_format=DocumentAnalysis,
        )

    else:
        response = client.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACT_LLM_PROMPT},
                {"role": "user", "content": f"Document:\n{text}"},
            ],
            response_format=DocumentAnalysis,
            reasoning_effort=reasoning_effort
        )

    return response.choices[0].message.parsed

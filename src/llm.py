import streamlit as st
from openai import OpenAI
from config import OPENAI_API_KEY
from schemas import DocumentAnalysis

client = OpenAI(api_key=OPENAI_API_KEY)

@st.cache_data(show_spinner=False)
def analyze(text: list[dict], model: str) -> DocumentAnalysis:
    response = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": 
            """
            You are analyzing a legal filing provided as Markdown extracted from a PDF.
            Headings, page breaks, and tables are preserved.
            Extract structured data into the requested schema.
            """},
            {"role": "user", "content": f"Document:\n{text}"},
        ],
        response_format=DocumentAnalysis,
    )

    return response.choices[0].message.parsed

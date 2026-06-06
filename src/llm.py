import base64

import anthropic
import streamlit as st
from config import ANTHROPIC_API_KEY, EXTRACT_LLM_PROMPT
from schemas import DocumentAnalysis

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


@st.cache_data(show_spinner=False)
def _analyze_json(pdf_bytes: bytes, model: str, effort: str | None) -> str | None:
    # Cache a plain JSON string (picklable) rather than the SDK's parsed object.
    # The PDF is uploaded directly; Claude reads each page as text + image.
    document = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf_bytes).decode("utf-8"),
        },
    }
    kwargs = {
        "model": model,
        "max_tokens": 8192 if effort is None else 16000,
        "system": EXTRACT_LLM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    document,
                    {"type": "text", "text": "Extract the fields from the attached filing."},
                ],
            }
        ],
        "output_format": DocumentAnalysis,
    }
    if effort is not None:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": effort}

    response = client.messages.parse(**kwargs)
    parsed = response.parsed_output
    return parsed.model_dump_json() if parsed is not None else None


def analyze(pdf_bytes: bytes, model: dict) -> DocumentAnalysis | None:
    raw = _analyze_json(pdf_bytes, model["id"], model["effort"])
    return DocumentAnalysis.model_validate_json(raw) if raw is not None else None

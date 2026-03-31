from typing import TypedDict

OPENAI_MODEL: str = "gpt-4o-mini"
OPENAI_MAX_TOKENS: int = 2048
OPENAI_TEMPERATURE: float = 0.1

CONFIDENCE_HIGH: float = 0.95
CONFIDENCE_MEDIUM: float = 0.75
CONFIDENCE_LOW: float = 0.50
CONFIDENCE_LLM: float = 0.70
CONFIDENCE_MISSING: float = 0.0

DETERMINISTIC_FIELDS: list[str] = [
    "case_number",
    "court_name",
    "hearing_date",
    "hearing_time",
    "hearing_location",
]

SEMANTIC_FIELDS: list[str] = [
    "case_name",
    "motion_name",
    "motion_summary",
]

ALL_FIELDS: list[str] = DETERMINISTIC_FIELDS + SEMANTIC_FIELDS

SOURCE_REGEX: str = "regex"
SOURCE_RULE: str = "rule"
SOURCE_LLM: str = "llm"
SOURCE_HYBRID: str = "hybrid"
SOURCE_MISSING: str = "missing"


class FieldResult(TypedDict):
    value: str | None
    confidence: float
    source: str


class ExtractionResult(TypedDict):
    case_name: str | None
    case_number: str | None
    court_name: str | None
    hearing_date: str | None
    hearing_time: str | None
    hearing_location: str | None
    motion_name: str | None
    motion_summary: str | None
    confidence: dict[str, float]
    source: dict[str, str]
    warnings: list[str]
    raw_text: str


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned

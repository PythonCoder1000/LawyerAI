from typing import TypedDict

APP_VERSION: str = "v0.0.0-beta.2"

OPENAI_MODEL: str = "gpt-5.4"
OPENAI_MAX_TOKENS: int = 2048
OPENAI_TEMPERATURE: float = 0.1

AVAILABLE_MODELS: list[str] = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5.4-nano",
    "gpt-5.4-mini",
    "gpt-5.4",
]

# Pricing per token (USD). Update these if OpenAI changes pricing.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    #                   (input $/token,          output $/token)
    "gpt-4o-mini":     (0.15  / 1_000_000,      0.60  / 1_000_000),
    "gpt-4o":          (2.50  / 1_000_000,      10.00 / 1_000_000),
    "gpt-5.4-nano":    (0.10  / 1_000_000,      0.40  / 1_000_000),
    "gpt-5.4-mini":    (0.20  / 1_000_000,      0.80  / 1_000_000),
    "gpt-5.4":         (2.00  / 1_000_000,      8.00  / 1_000_000),
}

# Live rate limit data populated from OpenAI response headers after each API call.
# Keyed by model name. Values: limit_requests (RPM), limit_tokens (TPM),
# remaining_requests, remaining_tokens.
model_rate_limits: dict[str, dict[str, int]] = {}

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
    cost: float
    input_tokens: int
    output_tokens: int


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned

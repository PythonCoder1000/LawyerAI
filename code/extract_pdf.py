import re
import json
import time
import fitz
import openai
from openai import OpenAI
from datetime import datetime
from pathlib import WindowsPath
from typing import Any

import utils
from parse_pdf import open_pdf, extract_text_by_page
from utils import (
    OPENAI_MODEL,
    OPENAI_MAX_TOKENS,
    OPENAI_TEMPERATURE,
    MODEL_PRICING,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_LLM,
    CONFIDENCE_MISSING,
    DETERMINISTIC_FIELDS,
    SEMANTIC_FIELDS,
    ALL_FIELDS,
    SOURCE_REGEX,
    SOURCE_RULE,
    SOURCE_LLM,
    SOURCE_HYBRID,
    SOURCE_MISSING,
    FieldResult,
    ExtractionResult,
    clean_value,
)

_openai_client: OpenAI | None = None

_total_cost: float = 0.0
_total_input_tokens: int = 0
_total_output_tokens: int = 0


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client

LINE_Y_TOLERANCE: float = 4.0
CAPTION_GAP_THRESHOLD: float = 30.0

_NULLABLE_STRING: dict[str, Any] = {
    "anyOf": [{"type": "string"}, {"type": "null"}],
}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "format": {
        "type": "json_schema",
        "name": "legal_notice_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "case_name": _NULLABLE_STRING,
                "case_number": _NULLABLE_STRING,
                "court_name": _NULLABLE_STRING,
                "hearing_date": _NULLABLE_STRING,
                "hearing_time": _NULLABLE_STRING,
                "hearing_location": _NULLABLE_STRING,
                "motion_name": _NULLABLE_STRING,
                "motion_summary": _NULLABLE_STRING,
            },
            "required": [
                "case_name", "case_number", "court_name",
                "hearing_date", "hearing_time", "hearing_location",
                "motion_name", "motion_summary",
            ],
            "additionalProperties": False,
        },
    },
}

CAPTION_FIELD_LABELS: re.Pattern[str] = re.compile(
    r"(?:date|time|dept\.?|department|judge|case\s*no\.?|hearing|calendar|assigned)\s*[.:]",
    re.IGNORECASE,
)

CASE_NUMBER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:Case\s*(?:No\.?|Number|#)\s*[:\-]?\s*)([A-Z0-9][\w\-\/\.]+)", re.IGNORECASE),
    re.compile(r"(?:No\.?\s*[:\-]?\s*)(\d{2,4}[\-\/][A-Z]{1,4}[\-\/]\d{3,10})", re.IGNORECASE),
    re.compile(r"\b(\d{2,4}[\-][A-Z]{2,5}[\-]\d{4,10})\b"),
    re.compile(r"\b([A-Z]{2,5}\d{2,4}[\-]\d{4,10})\b"),
]

DATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:hearing\s*date|date\s*of\s*hearing|set\s*for\s*hearing|hearing\s*(?:is\s*)?(?:set\s*for|on|scheduled))\s*[:\-]?\s*(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"(?:hearing\s*date|date\s*of\s*hearing|set\s*for\s*hearing)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", re.IGNORECASE),
    re.compile(r"(?:date|dated?)\s*[:\-]?\s*(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"(?:date|dated?)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", re.IGNORECASE),
    re.compile(r"(?:on)\s+(\w+\s+\d{1,2},?\s+\d{4})\s*(?:at|,)", re.IGNORECASE),
]

TIME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:hearing\s*time|time\s*of\s*hearing)\s*[:\-]?\s*(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?))", re.IGNORECASE),
    re.compile(r"(?:time)\s*[:\-]?\s*(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?))", re.IGNORECASE),
    re.compile(r"(?:at|@)\s*(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?))", re.IGNORECASE),
]

COURT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"((?:Superior|District|Circuit|Municipal|County|Supreme|Appellate|Family|Probate|Bankruptcy)\s+Court\s+(?:of|for|in)\s+[^\n]{3,80})", re.IGNORECASE),
    re.compile(r"((?:United\s+States\s+)?(?:District|Bankruptcy)\s+Court\s+(?:for\s+the\s+)?[^\n]{3,80})", re.IGNORECASE),
    re.compile(r"((?:SUPERIOR|DISTRICT|CIRCUIT|SUPREME|MUNICIPAL)\s+COURT[^\n]{0,100})", re.IGNORECASE),
]

BODY_LOCATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"located\s+at\s+([^\n,;]{5,120})", re.IGNORECASE),
    re.compile(r"(?:in\s+)?[Dd]epartment\s+\S+\s+of\s+(?:the\s+)?[^,]+,\s*located\s+at\s+([^\n]{5,120})", re.IGNORECASE),
    re.compile(r"(?:hearing\s*location|location)\s*[:\-]?\s*([^\n]{5,120})", re.IGNORECASE),
    re.compile(r"(?:courtroom|room)\s*[:\-]?\s*([^\n]{3,80})", re.IGNORECASE),
    re.compile(r"(?:remote\s*(?:appearance|hearing))\s*[:\-]?\s*([^\n]{5,120})", re.IGNORECASE),
]

ADDRESS_PATTERN: re.Pattern[str] = re.compile(
    r"(\d+\s+\w+(?:\s+\w+){0,4}\s+(?:Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Road|Rd\.?|Way|Place|Pl\.?|Circle|Cir\.?)[^\n]{0,60})",
    re.IGNORECASE,
)

DEPT_PATTERN: re.Pattern[str] = re.compile(
    r"(?:department|dept)\.?\s*[:\-]?\s*(\w+)",
    re.IGNORECASE,
)

SUSPICIOUS_LOCATION_WORDS: set[str] = {
    "restaurant", "cafe", "bakery", "salon", "shop", "store", "market",
    "pharmacy", "clinic", "hotel", "motel", "bar", "grill", "deli",
    "inc", "corp", "llc", "ltd", "dba", "co.",
    "plaintiff", "defendant", "petitioner", "respondent",
    "complainant", "appellant", "appellee",
}

WordTuple = tuple[float, float, float, float, str]
Line = list[WordTuple]


class PageRegions:
    def __init__(
        self,
        header: str,
        left: str,
        right: str,
        body: str,
        full: str,
        has_two_columns: bool,
    ):
        self.header = header
        self.left = left
        self.right = right
        self.body = body
        self.full = full
        self.has_two_columns = has_two_columns


def extract_page_words(page: Any) -> tuple[list[WordTuple], float, float]:
    rect = page.rect
    raw_words = page.get_text("words")
    words: list[WordTuple] = []
    for w in raw_words:
        words.append((float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])))
    return words, float(rect.width), float(rect.height)


def group_words_into_lines(words: list[WordTuple], y_tolerance: float = LINE_Y_TOLERANCE) -> list[Line]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w[1], w[0]))
    lines: list[Line] = []
    current_line: Line = [sorted_words[0]]
    current_y = sorted_words[0][1]

    for word in sorted_words[1:]:
        if abs(word[1] - current_y) <= y_tolerance:
            current_line.append(word)
        else:
            current_line.sort(key=lambda w: w[0])
            lines.append(current_line)
            current_line = [word]
            current_y = word[1]

    current_line.sort(key=lambda w: w[0])
    lines.append(current_line)
    return lines


def line_to_text(line: Line) -> str:
    return " ".join(w[4] for w in line)


def lines_to_text(lines: list[Line]) -> str:
    return "\n".join(line_to_text(ln) for ln in lines)


def detect_caption_boundary(lines: list[Line], page_width: float) -> float:
    midpoint = page_width / 2
    last_caption_y = 0.0

    for line in lines:
        left_words = [w for w in line if w[0] < midpoint]
        right_words = [w for w in line if w[0] >= midpoint]

        if left_words and right_words:
            left_edge = max(w[2] for w in left_words)
            right_edge = min(w[0] for w in right_words)
            if right_edge - left_edge >= CAPTION_GAP_THRESHOLD:
                last_caption_y = max(w[3] for w in line)
                continue

        if right_words:
            right_text = " ".join(w[4] for w in sorted(right_words, key=lambda w: w[0]))
            if CAPTION_FIELD_LABELS.search(right_text):
                last_caption_y = max(w[3] for w in line)

    return last_caption_y


def build_page_regions(lines: list[Line], page_width: float) -> PageRegions:
    caption_y = detect_caption_boundary(lines, page_width)
    midpoint = page_width / 2
    has_two_columns = caption_y > 0

    header_parts: list[str] = []
    left_parts: list[str] = []
    right_parts: list[str] = []
    body_parts: list[str] = []
    seen_right_content = False

    for line in lines:
        line_y = min(w[1] for w in line)

        if has_two_columns and line_y <= caption_y:
            left_words = [w for w in line if w[0] < midpoint - 5]
            right_words = [w for w in line if w[0] >= midpoint - 5]

            has_left = bool(left_words)
            has_right = bool(right_words)

            if has_right:
                seen_right_content = True

            if has_left and not has_right and not seen_right_content:
                header_parts.append(line_to_text(line))
            else:
                if has_left:
                    left_words.sort(key=lambda w: w[0])
                    left_parts.append(" ".join(w[4] for w in left_words))
                if has_right:
                    right_words.sort(key=lambda w: w[0])
                    right_parts.append(" ".join(w[4] for w in right_words))
        else:
            body_parts.append(line_to_text(line))

    full_text = lines_to_text(lines)

    return PageRegions(
        header="\n".join(header_parts),
        left="\n".join(left_parts),
        right="\n".join(right_parts),
        body="\n".join(body_parts),
        full=full_text,
        has_two_columns=has_two_columns,
    )


def parse_page1_layout(pdf_path: WindowsPath) -> PageRegions:
    document = fitz.open(pdf_path)
    if len(document) == 0:
        return PageRegions("", "", "", "", "", False)
    page = document[0]
    words, width, height = extract_page_words(page)
    if not words:
        fallback = str(page.get_text("text", sort=True))
        return PageRegions("", "", "", fallback, fallback, False)
    lines = group_words_into_lines(words)
    return build_page_regions(lines, width)


def get_motion_text(pdf_path: WindowsPath) -> str:
    pages_result = extract_text_by_page(pdf_path)
    total = len(pages_result["pages"])
    if total < 2:
        return ""
    parts: list[str] = []
    for page in pages_result["pages"]:
        if 2 <= page["page_num"] <= min(total, 4):
            parts.append(page["text"])
    text = "\n".join(parts)
    memo_match = re.search(r"memorandum\s+of\s+points\s+and\s+authorities", text, re.IGNORECASE)
    if memo_match:
        text = text[:memo_match.start()]
    return text


def get_full_raw_text(pdf_path: WindowsPath) -> str:
    pages_result = extract_text_by_page(pdf_path)
    return "\n".join(page["text"] for page in pages_result["pages"])


def validate_date(date_str: str) -> str | None:
    formats = [
        "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
        "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y",
    ]
    cleaned = date_str.strip().rstrip(".,;")
    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.strftime("%B %d, %Y")
        except ValueError:
            continue
    return cleaned


def validate_time(time_str: str) -> str | None:
    cleaned = time_str.strip().rstrip(".,;")
    normalized = re.sub(r"(\d{1,2}:\d{2})\s*(a\.?m\.?|p\.?m\.?)", r"\1 \2", cleaned, flags=re.IGNORECASE)
    normalized = re.sub(r"\.", "", normalized)
    for fmt in ["%I:%M %p", "%I:%M%p", "%H:%M"]:
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.strftime("%I:%M %p")
        except ValueError:
            continue
    return cleaned


def is_suspicious_location(value: str) -> bool:
    lower = value.lower()
    for word in SUSPICIOUS_LOCATION_WORDS:
        if word in lower:
            return True
    return False


def extract_case_number(right_text: str, left_text: str, full_text: str) -> FieldResult:
    for source_text in [right_text, left_text, full_text]:
        for pattern in CASE_NUMBER_PATTERNS:
            match = pattern.search(source_text)
            if match:
                value = clean_value(match.group(1))
                if value and len(value) >= 4:
                    labeled = bool(re.search(r"(?:case|no\.?|number|#)", match.group(0), re.IGNORECASE))
                    return {
                        "value": value,
                        "confidence": CONFIDENCE_HIGH if labeled else CONFIDENCE_MEDIUM,
                        "source": SOURCE_REGEX,
                    }
    return {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}


def extract_court_name(header_text: str, full_text: str) -> FieldResult:
    for source_text in [header_text, full_text]:
        for pattern in COURT_PATTERNS:
            match = pattern.search(source_text)
            if match:
                value = clean_value(match.group(1))
                if value:
                    value = re.sub(r"^IN\s+THE\s+", "", value, flags=re.IGNORECASE).strip()
                    return {
                        "value": value,
                        "confidence": CONFIDENCE_HIGH,
                        "source": SOURCE_REGEX,
                    }
    return {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}


def extract_hearing_date(right_text: str, body_text: str) -> FieldResult:
    for source_text in [right_text, body_text]:
        for pattern in DATE_PATTERNS:
            match = pattern.search(source_text)
            if match:
                raw = match.group(1)
                validated = validate_date(raw)
                if validated:
                    labeled = bool(re.search(r"(?:hearing|date)", match.group(0), re.IGNORECASE))
                    return {
                        "value": validated,
                        "confidence": CONFIDENCE_HIGH if labeled else CONFIDENCE_LOW,
                        "source": SOURCE_REGEX,
                    }
    return {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}


def extract_hearing_time(right_text: str, body_text: str) -> FieldResult:
    for source_text in [right_text, body_text]:
        for pattern in TIME_PATTERNS:
            match = pattern.search(source_text)
            if match:
                raw = match.group(1)
                validated = validate_time(raw)
                if validated:
                    labeled = bool(re.search(r"(?:hearing|time)", match.group(0), re.IGNORECASE))
                    return {
                        "value": validated,
                        "confidence": CONFIDENCE_HIGH if labeled else CONFIDENCE_MEDIUM,
                        "source": SOURCE_REGEX,
                    }
    return {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}


def extract_department(right_text: str) -> str | None:
    match = DEPT_PATTERN.search(right_text)
    if match:
        return clean_value(match.group(1))
    return None


def extract_hearing_location(
    body_text: str,
    motion_text: str,
    department: str | None,
    warnings: list[str],
) -> FieldResult:
    combined = body_text + "\n" + motion_text

    for pattern in BODY_LOCATION_PATTERNS:
        match = pattern.search(combined)
        if match:
            value = clean_value(match.group(1))
            if value and not is_suspicious_location(value):
                if department and not re.search(r"department|dept", value, re.IGNORECASE):
                    value = f"Department {department}, {value}"
                return {
                    "value": value,
                    "confidence": CONFIDENCE_HIGH,
                    "source": SOURCE_REGEX,
                }
            if value and is_suspicious_location(value):
                warnings.append(f"Rejected suspicious location value: {value}")

    address_match = ADDRESS_PATTERN.search(combined)
    if address_match:
        value = clean_value(address_match.group(1))
        if value and not is_suspicious_location(value):
            if department:
                value = f"Department {department}, {value}"
            return {
                "value": value,
                "confidence": CONFIDENCE_MEDIUM,
                "source": SOURCE_REGEX,
            }

    if department:
        return {
            "value": f"Department {department}",
            "confidence": CONFIDENCE_LOW,
            "source": SOURCE_RULE,
        }

    return {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}


def run_deterministic_extraction(
    regions: PageRegions,
    motion_text: str,
    warnings: list[str],
) -> dict[str, FieldResult]:
    department = extract_department(regions.right)

    if not regions.has_two_columns:
        warnings.append("No two-column layout detected on page 1; using full text for extraction")

    right_source = regions.right if regions.has_two_columns else regions.full
    left_source = regions.left if regions.has_two_columns else regions.full
    header_source = regions.header if regions.header else regions.full
    body_source = regions.body if regions.body else regions.full

    return {
        "case_number": extract_case_number(right_source, left_source, regions.full),
        "court_name": extract_court_name(header_source, regions.full),
        "hearing_date": extract_hearing_date(right_source, body_source),
        "hearing_time": extract_hearing_time(right_source, body_source),
        "hearing_location": extract_hearing_location(body_source, motion_text, department, warnings),
    }


def validate_extraction(
    results: dict[str, FieldResult],
    regions: PageRegions,
    warnings: list[str],
) -> dict[str, FieldResult]:
    location = results.get("hearing_location", {})
    if location.get("value") and is_suspicious_location(location["value"]): # type: ignore
        warnings.append(f"Location contains suspicious text: {location['value']}")
        results["hearing_location"] = {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}

    date_result = results.get("hearing_date", {})
    if date_result.get("value"):
        try:
            parsed = datetime.strptime(date_result["value"], "%B %d, %Y") # type: ignore
            if parsed.year < 2000 or parsed.year > 2100:
                warnings.append(f"Hearing date has implausible year: {date_result['value']}")
                results["hearing_date"]["confidence"] = CONFIDENCE_LOW
        except ValueError:
            pass

    time_result = results.get("hearing_time", {})
    if time_result.get("value"):
        if not re.search(r"\d{1,2}:\d{2}", time_result["value"]): # type: ignore
            warnings.append(f"Hearing time has unexpected format: {time_result['value']}")
            results["hearing_time"]["confidence"] = CONFIDENCE_LOW

    return results


def build_semantic_prompt(
    regions: PageRegions,
    motion_text: str,
    extracted: dict[str, FieldResult],
    fields_needed: list[str],
) -> str:
    already_found: dict[str, str | None] = {}
    for field, result in extracted.items():
        if result["value"] is not None and result["confidence"] >= CONFIDENCE_MEDIUM:
            already_found[field] = result["value"]

    missing_list = ", ".join(fields_needed)
    found_json = json.dumps(already_found, indent=2)

    context_parts: list[str] = []

    page1_fields = {"case_name", "case_number", "court_name", "hearing_date", "hearing_time", "hearing_location"}
    if any(f in fields_needed for f in page1_fields):
        if regions.has_two_columns:
            if regions.header:
                context_parts.append(f"=== PAGE 1 HEADER (Court Name) ===\n{regions.header}")
            context_parts.append(f"=== PAGE 1 LEFT CAPTION (Parties & Motion Title) ===\n{regions.left}")
            context_parts.append(f"=== PAGE 1 RIGHT CAPTION (Case Info & Hearing Fields) ===\n{regions.right}")
            if regions.body:
                context_parts.append(f"=== PAGE 1 BODY (Notice Text) ===\n{regions.body}")
        else:
            context_parts.append(f"=== PAGE 1 ===\n{regions.full}")

    if any(f in fields_needed for f in ["motion_name", "motion_summary", "hearing_location"]):
        if motion_text.strip():
            context_parts.append(f"=== MOTION TEXT (Pages 2+) ===\n{motion_text}")

    context = "\n\n".join(context_parts)

    return f"""You are a legal document analysis system specializing in extracting structured metadata from U.S. court filings and legal notices. Your task is precise field extraction — accuracy matters more than completeness.

CONTEXT:
The document below is a legal notice or court filing. Some fields have already been extracted by a deterministic parser and are listed below. You must extract the remaining fields.

ALREADY EXTRACTED (verified by regex — return null for these unless you find a clear error):
{found_json}

FIELDS TO EXTRACT: {missing_list}

EXTRACTION RULES:

1. ACCURACY: Only extract values explicitly stated in the document. Never infer, guess, or fabricate. If a field cannot be found, return null.

2. FIELD-SPECIFIC GUIDANCE:
   - "case_name": The full case caption with all party names. Use "v." as the separator for adversarial cases (e.g., "Smith v. Jones"). For non-adversarial matters use the proper format (e.g., "In re Estate of Smith", "In the Matter of Jones"). Include all plaintiffs and defendants if listed.
   - "case_number": The court's docket or case number, typically after "Case No.", "No.", or "#".
   - "court_name": The full official name of the court (e.g., "Superior Court of California, County of Los Angeles"). Omit any "IN THE" prefix.
   - "hearing_date": The scheduled hearing date. Return in "Month DD, YYYY" format (e.g., "January 15, 2025"). If multiple dates appear, use the one most clearly associated with the hearing.
   - "hearing_time": The scheduled hearing time. Return in "HH:MM AM/PM" format (e.g., "09:30 AM").
   - "hearing_location": The physical location of the hearing. Look for street addresses, "located at" phrases, department or courtroom numbers, or remote hearing URLs. Do NOT use party names, attorney names, firm names, or business names as locations.
   - "motion_name": The formal title of the motion as stated in the document (e.g., "Motion for Summary Judgment", "Demurrer to Complaint").
   - "motion_summary": A concise 1-3 sentence factual summary of what the motion requests and why. State the relief sought and the key legal basis. Paraphrase in plain language — do not quote the document verbatim.

3. AMBIGUITY: If multiple possible values exist for a field (e.g., multiple dates), prefer the value most clearly labeled as hearing-related.

DOCUMENT TEXT:
{context}"""


def _parse_header_int(headers: Any, key: str) -> int:
    val = headers.get(key)
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def call_openai_structured(prompt: str) -> dict[str, Any]:
    global _total_cost, _total_input_tokens, _total_output_tokens
    max_retries = 5
    for attempt in range(max_retries):
        try:
            raw_response = get_openai_client().responses.with_raw_response.create(
                model=OPENAI_MODEL,
                input=[{"role": "user", "content": prompt}],
                text=EXTRACTION_SCHEMA,  # type: ignore
                max_output_tokens=OPENAI_MAX_TOKENS,
                temperature=OPENAI_TEMPERATURE,
                store=False,
            )
            response = raw_response.parse()

            # Store live rate limits from OpenAI response headers
            headers = raw_response.headers
            utils.model_rate_limits[OPENAI_MODEL] = {
                "limit_requests": _parse_header_int(headers, "x-ratelimit-limit-requests"),
                "limit_tokens": _parse_header_int(headers, "x-ratelimit-limit-tokens"),
                "remaining_requests": _parse_header_int(headers, "x-ratelimit-remaining-requests"),
                "remaining_tokens": _parse_header_int(headers, "x-ratelimit-remaining-tokens"),
            }

            if response.usage:
                _total_input_tokens += response.usage.input_tokens
                _total_output_tokens += response.usage.output_tokens
                input_price, output_price = MODEL_PRICING.get(
                    OPENAI_MODEL, (0.0, 0.0),
                )
                _total_cost += (
                    response.usage.input_tokens * input_price
                    + response.usage.output_tokens * output_price
                )
            raw = response.output_text
            return json.loads(raw)
        except openai.RateLimitError:
            print("OpenAI rate limit reached! Retrying right now...")
            time.sleep(1)
    raise RuntimeError("OpenAI rate limit exceeded after multiple retries")


def run_semantic_extraction(
    regions: PageRegions,
    motion_text: str,
    extracted: dict[str, FieldResult],
    fields_needed: list[str],
    warnings: list[str],
) -> dict[str, FieldResult]:
    results: dict[str, FieldResult] = {}

    if not fields_needed:
        return results

    prompt = build_semantic_prompt(regions, motion_text, extracted, fields_needed)

    try:
        parsed = call_openai_structured(prompt)
    except Exception as e:
        warnings.append(f"OpenAI API call failed: {e}")
        for field in fields_needed:
            results[field] = {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}
        return results

    for field in fields_needed:
        value = parsed.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            results[field] = {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_LLM}
        else:
            cleaned = clean_value(str(value))
            if field == "hearing_date" and cleaned:
                cleaned = validate_date(cleaned)
            elif field == "hearing_time" and cleaned:
                cleaned = validate_time(cleaned)
            confidence = CONFIDENCE_LLM
            if field == "hearing_location" and cleaned and is_suspicious_location(cleaned):
                warnings.append(f"LLM returned suspicious location: {cleaned}")
                cleaned = None
                confidence = CONFIDENCE_MISSING
            results[field] = {
                "value": cleaned,
                "confidence": confidence,
                "source": SOURCE_LLM,
            }

    return results


def merge_results(
    deterministic: dict[str, FieldResult],
    semantic: dict[str, FieldResult],
) -> dict[str, FieldResult]:
    merged: dict[str, FieldResult] = {}

    for field in ALL_FIELDS:
        det = deterministic.get(field)
        sem = semantic.get(field)

        if det and det["value"] is not None and det["confidence"] >= CONFIDENCE_MEDIUM:
            if sem and sem["value"] is not None:
                merged[field] = {
                    "value": det["value"],
                    "confidence": det["confidence"],
                    "source": SOURCE_HYBRID,
                }
            else:
                merged[field] = det
        elif sem and sem["value"] is not None:
            merged[field] = sem
        elif det and det["value"] is not None:
            merged[field] = det
        else:
            merged[field] = {"value": None, "confidence": CONFIDENCE_MISSING, "source": SOURCE_MISSING}

    return merged


def build_output(merged: dict[str, FieldResult], raw_text: str, warnings: list[str]) -> ExtractionResult:
    for field in ALL_FIELDS:
        if merged.get(field, {}).get("value") is None:
            warnings.append(f"Missing required field: {field}")

    return {
        "case_name": merged["case_name"]["value"],
        "case_number": merged["case_number"]["value"],
        "court_name": merged["court_name"]["value"],
        "hearing_date": merged["hearing_date"]["value"],
        "hearing_time": merged["hearing_time"]["value"],
        "hearing_location": merged["hearing_location"]["value"],
        "motion_name": merged["motion_name"]["value"],
        "motion_summary": merged["motion_summary"]["value"],
        "confidence": {field: merged[field]["confidence"] for field in ALL_FIELDS},
        "source": {field: merged[field]["source"] for field in ALL_FIELDS},
        "warnings": warnings,
        "raw_text": raw_text,
        "cost": _total_cost,
        "input_tokens": _total_input_tokens,
        "output_tokens": _total_output_tokens,
    }


def extract_notice(pdf_path: WindowsPath) -> ExtractionResult:
    global _total_cost, _total_input_tokens, _total_output_tokens
    _total_cost = 0.0
    _total_input_tokens = 0
    _total_output_tokens = 0

    warnings: list[str] = []

    regions = parse_page1_layout(pdf_path)
    motion_text = get_motion_text(pdf_path)
    raw_text = get_full_raw_text(pdf_path)

    if not regions.full.strip():
        warnings.append("Page 1 produced no extractable text")

    deterministic = run_deterministic_extraction(regions, motion_text, warnings)
    deterministic = validate_extraction(deterministic, regions, warnings)

    fields_for_llm: list[str] = list(SEMANTIC_FIELDS)

    for field in DETERMINISTIC_FIELDS:
        result = deterministic.get(field)
        if result is None or result["value"] is None or result["confidence"] < CONFIDENCE_MEDIUM:
            fields_for_llm.append(field)

    semantic = run_semantic_extraction(
        regions, motion_text, deterministic, fields_for_llm, warnings,
    )

    merged = merge_results(deterministic, semantic)

    return build_output(merged, raw_text, warnings)


def run_pipeline() -> ExtractionResult:
    pdf_path = open_pdf()
    return extract_notice(pdf_path)


if __name__ == "__main__":
    result = run_pipeline()
    output = json.dumps(result, indent=2, ensure_ascii=False)
    print(output)
    print(f"\nTotal OpenAI API cost: ${result['cost']:.6f}")

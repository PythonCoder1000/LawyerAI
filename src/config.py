import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

EXTRACT_LLM_PROMPT = """\
You are a meticulous legal-document data extractor. Your job is to read a legal
filing (provided as Markdown converted from a PDF) and return structured fields
exactly matching the requested schema.

## Input
- The text is Markdown extracted from a PDF. Headings (`#`), tables, page breaks,
    and line breaks are preserved but may be noisy: hyphenation across lines,
    duplicated headers/footers, page numbers, OCR artifacts, and stray whitespace
    are common. Treat them as noise — do not let them corrupt extracted values.
- The caption block (top of the first page) is the most reliable source for
    case_name, case_number, and court_name. The notice/hearing block is the most
    reliable source for hearing_date, hearing_time, and hearing_location.

## Extraction rules
1. **Verbatim, then normalized.** Copy values as written in the document.
    Normalize only obvious noise: collapse internal whitespace, remove trailing
    punctuation, rejoin words split by line-break hyphens (e.g., "plain-\\ntiff"
    → "plaintiff"). Preserve original capitalization, party names, and "v." vs
    "vs." styling.
2. **Never infer or guess.** If a field is not clearly present in the document,
    return `null`. Do not synthesize from related context, do not translate, do
    not abbreviate, do not expand abbreviations.
3. **Pick the canonical occurrence.** If a value appears multiple times (e.g.,
    case number in caption and footer), use the version from the caption /
    primary heading. If versions disagree, prefer the most complete one.
4. **Dates and times.** Return dates in `YYYY-MM-DD` format when the full date
    is unambiguous; otherwise return the date string as written. Return times in
    `h:mm AM/PM` format (e.g., `9:30 AM`); preserve timezone if stated
    (e.g., `9:30 AM PT`).
5. **Hearing location.** Include department/courtroom and address if both are
    given (e.g., "Dept. 17, 111 N. Hill St., Los Angeles, CA 90012"). If only
    one is given, return what is present.
6. **Motion name.** Use the exact title of the motion/filing as it appears on
    the caption or notice (e.g., "Defendant's Motion to Compel Further Responses
    to Requests for Production, Set One").
7. **Motion summary.** Write a neutral 2-4 sentence summary of what the motion
    asks the court to do and the key grounds. No quotations, no recommendations,
    no legal advice, no information that is not in the document.

## Output
Return only the structured fields defined by the schema. Use `null` for any
field you cannot extract with high confidence. Do not add commentary, do not
wrap the output in prose, do not include fields outside the schema.\
"""

MODELS = [
    {
        "id": "gpt-5",
        "label": "General Documents",
        "caption": "For general use across all documents",
        "reasoning_effort": "medium",
    },
    {
        "id": "o3",
        "label": "Complex Documents",
        "caption": "For documents with complex legal situations",
        "reasoning_effort": "high",
    },
    {
        "id": "gpt-4.1",
        "label": "Long Documents",
        "caption": "For 200+ page filings",
        "reasoning_effort": None,
    },
]

"""Batch-test the extraction pipeline against a folder of PDFs.

Runs every PDF in ``tests/data`` through all three configured models
(General, Complex/high-reasoning, and Long) concurrently, then writes the
combined results to ``tests/results/results-<timestamp>.json``.

Usage (from the repo root):
    python src/test.py
"""

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# llm.py's cached functions log warnings ("No runtime found", "missing
# ScriptRunContext") when run outside `streamlit run` — harmless here.
# logging.disable() overrides every logger's level globally, so it silences the
# warning Streamlit emits while being imported; we restore logging right after.
logging.disable(logging.WARNING)
from config import MODELS  # noqa: E402
from llm import analyze  # noqa: E402

logging.disable(logging.NOTSET)
# Keep Streamlit quiet for the cache warnings raised on each analyze() call too.
logging.getLogger("streamlit").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "tests" / "data"
RESULTS_DIR = ROOT / "tests" / "results"

# Network-bound Anthropic calls release the GIL, so threads give real
# parallelism. Cap concurrency to stay friendly with API rate limits.
MAX_WORKERS = 8


def run_one(pdf_path: Path, model: dict) -> dict:
    """Analyze a single PDF with one model and return a serializable record."""
    started = time.perf_counter()
    result = analyze(pdf_path.read_bytes(), model)
    elapsed = round(time.perf_counter() - started, 2)

    return {
        "pdf": pdf_path.name,
        "model_label": model["label"],
        "model_id": model["id"],
        "effort": model["effort"],
        "elapsed_seconds": elapsed,
        "result": result.model_dump(mode="json") if result is not None else None,
    }


def main() -> None:
    if not DATA_DIR.exists():
        sys.exit(f"No data directory found at {DATA_DIR}")

    pdfs = sorted(DATA_DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDF files found in {DATA_DIR}")

    jobs = [(pdf, model) for pdf in pdfs for model in MODELS]
    print(
        f"Running {len(pdfs)} PDF(s) x {len(MODELS)} model(s) "
        f"= {len(jobs)} analyses (up to {MAX_WORKERS} in parallel)...\n"
    )

    results: list[dict] = []
    errors: list[dict] = []

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as pool:
        futures = {
            pool.submit(run_one, pdf, model): (pdf, model) for pdf, model in jobs
        }
        for future in as_completed(futures):
            pdf, model = futures[future]
            try:
                record = future.result()
            except Exception as error:  # noqa: BLE001 - record any failure
                print(f"  ✗ {pdf.name} — {model['label']}: {error}")
                errors.append(
                    {
                        "pdf": pdf.name,
                        "model_label": model["label"],
                        "error": str(error),
                    }
                )
            else:
                print(
                    f"  ✓ {pdf.name} — {model['label']} "
                    f"({record['elapsed_seconds']}s)"
                )
                results.append(record)

    # Stable ordering in the output: by PDF, then by model.
    order = {model["label"]: i for i, model in enumerate(MODELS)}
    results.sort(key=lambda r: (r["pdf"], order.get(r["model_label"], 0)))

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_dir": str(DATA_DIR),
        "pdf_count": len(pdfs),
        "models": [model["label"] for model in MODELS],
        "total_analyses": len(jobs),
        "succeeded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / f"results-{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print(
        f"\nDone: {len(results)} succeeded, {len(errors)} failed.\n"
        f"Saved all data to {out_path}"
    )


if __name__ == "__main__":
    main()

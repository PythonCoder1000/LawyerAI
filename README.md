# LawyerAI - Legal Notice Extraction Pipeline

## Prerequisites

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Your OpenAI API Key

The pipeline uses the OpenAI Responses API with strict JSON schema for structured extraction. You need an API key from [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys).

Set it as an environment variable:

**Windows (PowerShell):**
```powershell
$env:OPENAI_API_KEY = "sk-your-key-here"
```

**Windows (Command Prompt):**
```cmd
set OPENAI_API_KEY=sk-your-key-here
```

To make it permanent on Windows:
1. Open Start and search for "Environment Variables"
2. Click "Edit the system environment variables"
3. Click "Environment Variables"
4. Under "User variables", click "New"
5. Variable name: `OPENAI_API_KEY`
6. Variable value: your API key

**macOS / Linux:**
```bash
export OPENAI_API_KEY="sk-your-key-here"
```

Or add it to your `~/.bashrc` / `~/.zshrc` for persistence.

## Privacy

All API calls are made with `store=False`, which means OpenAI will not store your inputs or outputs for training or any other purpose. Your legal documents are not retained on OpenAI's servers after the response is returned.

## Usage

```bash
cd code
python extract_pdf.py
```

A file dialog will open. Select a legal notice PDF and the pipeline will extract case information and print structured JSON output.

## Output

The pipeline returns a JSON object with:
- `case_name`, `case_number`, `court_name` - case identification
- `hearing_date`, `hearing_time`, `hearing_location` - hearing details
- `motion_name`, `motion_summary` - motion information
- `confidence` - per-field confidence scores (0.0 to 1.0)
- `source` - extraction method used per field (`regex`, `rule`, `llm`, `hybrid`, `missing`)
- `warnings` - any issues encountered during extraction
- `raw_text` - the text that was taken from the pdf

## Building to EXE

To build LawyerAI as a standalone executable:

### 1. Install PyInstaller

```bash
pip install pyinstaller
```

### 2. Uninstall pathlib

PyInstaller conflicts with the `pathlib` package on PyPI. If you have it installed, remove it:

```bash
pip uninstall pathlib
```

This only removes the third-party backport. Python 3 includes `pathlib` in the standard library, so nothing will break.

### 3. Run the build script

```bash
python build.py
```

The executable will be created at `dist/LawyerAI.exe`.

# App (EXE)

LawyerAI includes a graphical interface for extracting case information from court notice PDFs without using the command line.

## Features

- **PDF Browse & Extract** - Select any legal notice PDF and extract structured case fields with one click
- **Model Selector** - Choose between OpenAI models directly in the app: `gpt-4o-mini`, `gpt-4o`, `gpt-5.4-nano`, `gpt-5.4-mini`, `gpt-5.4`
- **Field Cards** - Each extracted field is displayed with its value, confidence score, and extraction source (regex, LLM, hybrid, etc.)
- **API Cost Tracking** - Shows the total OpenAI API cost for each extraction at the bottom of the window
- **Rate Limit Handling** - Automatically retries when OpenAI returns a 429 rate limit error, with a visible status message
- **Error Popups** - User-friendly error dialogs for common issues (invalid API key, connection errors, missing files)
- **Export JSON** - Save extraction results to a JSON file
- **About Dialog** - Available under Help > About with version info

## Output Fields

The app displays the following extracted fields:

| Field            | Description                               |
|------------------|-------------------------------------------|
| Case Name        | Full party names (e.g., "Smith v. Jones") |
| Case Number      | Court case identifier                     |
| Court Name       | Name of the court                         |
| Hearing Date     | Scheduled hearing date                    |
| Hearing Time     | Scheduled hearing time                    |
| Hearing Location | Court address or department               |
| Motion Name      | Title of the motion                       |
| Motion Summary   | Concise summary of the motion's purpose   |

Each field shows a **confidence score** (0-100%) and the **extraction source**:
- **REGEX** - Extracted via pattern matching (most reliable)
- **RULE** - Extracted via document structure rules
- **LLM** - Extracted via OpenAI language model
- **HYBRID** - Confirmed by both regex and LLM
- **MISSING** - Could not be found

## Configuration

Model settings can be changed in `code/utils.py`:
- `OPENAI_MODEL` - Default OpenAI model (default: `gpt-5.4`)
- `OPENAI_MAX_TOKENS` - Max output tokens
- `OPENAI_TEMPERATURE` - Sampling temperature (lower = more deterministic)
- `MODEL_PRICING` - Per-token pricing for cost tracking (update if OpenAI changes pricing)

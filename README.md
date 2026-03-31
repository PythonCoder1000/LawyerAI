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

## Configuration

Model settings can be changed in `code/utils.py`:
- `OPENAI_MODEL` - OpenAI model name (default: `gpt-4o-mini`)
- `OPENAI_MAX_TOKENS` - max output tokens
- `OPENAI_TEMPERATURE` - sampling temperature (lower = more deterministic)

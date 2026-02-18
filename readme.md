# CBP Ruling Extractor (pta-cbp-parser)

## Prerequisites
- Windows 10/11
- Python 3.10+ recommended
- Microsoft Word installed (required for legacy `.doc` extraction via COM)
- Internet access (downloads CBP rulings)

## Setup (Git Repository)
1. Clone the repository
2. Copy `.env.example` and paste it with a changed file ending `.env`. 
3. Fill in your API keys in the `.env` file
4. Run `pip install -r requirements.txt`

## Setup (PowerShell)

Execute the below lines in the PowerShell line by line, to avoid errors (don’t paste them all at once).

```powershell
cd <unzipped-folder>
```

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
cd pta-cbp-parser
```

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## LLM mode (optional | Default Model: OpenAI gpt-5-nano)
LLM mode requires at least an OpenAI API key set in an environment variable named `OPENAI_API_KEY`, as that is treated as the default model (gpt-5-nano).

### Set for the current PowerShell session only
```powershell
$env:OPENAI_API_KEY="[paste_your_key_here]"
python -c "import os; print(os.getenv('OPENAI_API_KEY') is not None)"
```

To confirm that the proper key was set check:
```powershell
$env:OPENAI_API_KEY
```


Expected Output is "True" -> there is a Key set

It is also necessary to set the organization_id and project_id 

```powershell
$env:OPENAI_ORGANIZATION_ID = "[org-your-org-id-here]"
$env:OPENAI_PROJECT_ID = "[proj-your-project-id-here]" 
```

## Run

The pipeline is orchestrated via `extract_rulings.py`. Jurisdiction defaults to `ny`. Optionally use `--llm` for OpenAI-assisted extraction alongside regex — this improves accuracy but costs approximately $0.06 per 4 rulings (last checked 07.01.2026).

### REGEX only (fast baseline)
```powershell
python .\extract_rulings.py
```

### REGEX + LLM extraction
```powershell
python .\extract_rulings.py --llm
```

### REGEX + Excel review report
```powershell
python .\extract_rulings.py --excel
```

### REGEX + LLM + Excel review report (full run)
```powershell
python .\extract_rulings.py --llm --excel
```

### Specify jurisdiction explicitly (default is ny)
```powershell
python .\extract_rulings.py --jurisdiction ny
python .\extract_rulings.py --jurisdiction ca
```

### Run fetcher tier comparison report
```powershell
python .\extract_rulings.py --fetchers_report
```

### Enable performance/cost logging
```powershell
python .\extract_rulings.py --llm --performance-log
```

### Custom base directory
```powershell
python .\extract_rulings.py --base_dir "C:\path\to\project"
```

### Combined example (full run, explicit jurisdiction, with logging)
```powershell
python .\extract_rulings.py --jurisdiction ny --llm --excel --performance-log
```

## Clear Cached Ruling Texts (Optional)
```powershell
python shared\clean_cache.py
```

If a cache file cannot be deleted, close Microsoft Word and end any lingering WINWORD.EXE, then re-run the clean command.
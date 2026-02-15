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

## Run (No Excel Review Report)

The main function is being orchastrated and coordinated via "extract_rulings.py". Optionally with a "--llm" flag the perplexity LLM extraction method can be used to have multiple indicators for each ruling extraction.

Each "--llm" run runs cost of approximately $0.06 for 4 rulings (last checked 07.01.2026), so it is a cost decision. The results were generally more accurate though.

 It can be operated as seen below:


### REGEX Only Extraction
```powershell
python .\extract_rulings.py
```
### Optional: Perplexity LLM API Extraction
```powershell
python .\extract_rulings.py --llm
``` 

## Run (with Excel Review Report)

### REGEX Only Extraction + Excel Review
```powershell
python .\extract_rulings.py --excel
```

### Optional: Perplexity LLM API Extraction + Excel Review
```powershell
python .\extract_rulings.py --excel --llm
```

## Clear Cached Ruling Texts (Optional)
```powershell
python .\cbp_parser\clean_cache.py
```

If a cache file cannot be deleted, close Microsoft Word and end any lingering WINWORD.EXE, then re-run the clean command.
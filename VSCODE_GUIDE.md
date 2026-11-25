# FinGuard — VS Code Quick Start

## Requirements
- Windows 10/11
- Python 3.11.x (recommended; use the same interpreter for install and run)
- VS Code with the Python extension
- A Gemini API key only if you want live Gemini responses. The project has a fallback mode without one.

## 1. Open the folder
Extract this ZIP, then in VS Code choose **File → Open Folder** and select the `FinGuard_VSCode` folder.

## 2. Create and activate a virtual environment (PowerShell terminal)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If PowerShell blocks activation, run this for the current terminal only:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 3. Configure environment (optional)
Copy `.env.example` to `.env` and replace `your_gemini_api_key_here` with your Gemini API key. Do not commit `.env` or share it. Plaid credentials are not required for the included mock data. Langfuse credentials are optional.

## 4. Run the frontend
```powershell
python -m streamlit run ui/app.py
```
Open http://localhost:8501.

## 5. Run the API (optional, separate terminal)
```powershell
python -m uvicorn backend.api:app --reload --port 8000
```
Open http://localhost:8000/docs. The Streamlit UI can run without starting the API separately.

## 6. Run the benchmark (optional)
```powershell
python evaluation/benchmark.py
```

## VS Code shortcuts
Use **Run and Debug** (`Ctrl+Shift+D`) and choose a FinGuard launch configuration, or run the commands above in the integrated terminal.

## What is included
- `agents/`: 11 agent implementations and orchestrator
- `core/`: shared state, guardrails, A2A messages, callbacks, and observability
- `mcp_service/`: local MCP-compatible tools and client/server
- `ui/`: Streamlit frontend
- `backend/`: FastAPI REST API
- `data/`: mock financial data used at runtime
- `evaluation/`: optional benchmark and scenarios
- `.vscode/`, `.streamlit/`: editor and UI configuration

Generated trace logs, deployment-only files, and launcher scripts were excluded to keep the local development folder focused. Runtime traces are recreated automatically.

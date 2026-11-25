# FinGuard Native ADK + CrewAI migration patch

This patch replaces the *claim* that custom base wrappers are ADK/CrewAI agents with a native execution layer:

- `agents/native_framework_runtime.py` creates a real Google ADK `Agent` and runs it with `InMemoryRunner` for each ADK specialist.
- The same module creates a real CrewAI `Agent`, `Task`, and `Crew` for each CrewAI specialist.
- The existing specialist classes have been renamed to `ADKDomainService` / `CrewAIDomainService` base classes. These are deterministic business-logic services, not framework agents.
- Each native framework agent must call `execute_financial_operation`; that tool invokes the audited calculation service and updates `FinGuardState`. The framework agent cannot make up the numerical result.
- Set `FINGUARD_NATIVE_FRAMEWORKS=true` in `.env` to use native framework execution. Set it to `false` for offline deterministic benchmark/debugging without API calls.

## Windows PowerShell setup

1. Extract this ZIP to a new folder (keep a backup of the original).
2. Create/activate a Python 3.11 virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3. Create `.env` by copying `.env.example`, then set `GEMINI_API_KEY` locally. Do not commit `.env` or share the key.
4. Set `FINGUARD_NATIVE_FRAMEWORKS=true`.
5. Run the backend:

```powershell
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

6. In another terminal run Streamlit:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run ui/app.py
```

7. Test `http://127.0.0.1:8000/docs`, submit a small purchase request, and verify that `agents_executed` contains each specialist and that traces show the run. Then run the benchmark in native mode; it makes live model calls and may incur API cost/latency.

## Important technical scope

This is a staged migration, not a claim that the 11 financial algorithms have been rewritten as LLM reasoning. The framework objects are native and execute their tools; deterministic calculation logic remains in the specialist domain-service classes for auditability. The A2A bus remains a custom in-process message bus, not a verified network A2A transport. Native framework execution requires a working API key and compatible installed dependencies. If a framework refuses to call its required tool, the runtime raises an error rather than silently claiming success.

## Files changed

- `agents/native_framework_runtime.py` (new): native ADK and CrewAI runtime.
- `agents/orchestrator.py`: routes each specialist through the native runtime when enabled.
- `agents/adk_framework/base.py` and its six imports: renamed to `ADKDomainService`.
- `agents/crewai_framework/crew_bridge.py` and its five imports: renamed to `CrewAIDomainService`.
- `requirements.txt`: adds `google-adk`, `google-genai`, and CrewAI Google GenAI extras.
- `.env.example`: documents native mode and model configuration.

## If dependency resolution fails

Do not randomly upgrade individual OpenTelemetry packages. Capture the full output of `pip install -r requirements.txt` and `pip check`; then pin a mutually compatible set for your exact Python environment. The ADK and CrewAI package ecosystems evolve, so dependency resolution should be tested in a fresh virtual environment.

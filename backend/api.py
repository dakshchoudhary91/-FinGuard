"""
FinGuard FastAPI Backend Service.
Exposes RESTful endpoints for purchase evaluation, observability traces,
A2A message transcripts, and benchmark reports.
"""

import os
import sys
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure FinGuard root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.orchestrator import default_orchestrator
from core.state import FinGuardVerdict, FinGuardState
from core.observability import default_observability
from core.protocol_a2a import default_a2a_bus

app = FastAPI(
    title="FinGuard Multi-Agent Financial Decision Engine",
    description="11-agent cooperative system using Google ADK and CrewAI interoperating via A2A protocol.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PurchaseEvaluationRequest(BaseModel):
    item_name: str = Field(..., example="Designer Sneakers")
    amount: float = Field(..., gt=0, example=250.00)
    category: str = Field(default="Shopping & Discretionary", example="Shopping & Discretionary")
    urgency: str = Field(default="low", example="low")
    notes: Optional[str] = Field(default="", example="Rent is due in 3 days")
    session_id: Optional[str] = Field(default="user_web_session")


class EvaluationResponse(BaseModel):
    verdict: FinGuardVerdict
    trace_id: str
    total_latency_ms: float
    guardrails_passed: bool
    agents_executed: List[str]


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "FinGuard Multi-Agent Engine",
        "agents_count": 11,
        "frameworks": ["Google ADK", "CrewAI", "Model Context Protocol (MCP)"],
        "a2a_protocol_version": "A2A/1.0"
    }


@app.post("/evaluate", response_model=EvaluationResponse)
def evaluate_purchase(req: PurchaseEvaluationRequest):
    try:
        state = default_orchestrator.evaluate_purchase(
            item_name=req.item_name,
            amount=req.amount,
            category=req.category,
            urgency=req.urgency,
            notes=req.notes or "",
            session_id=req.session_id or "user_web_session"
        )

        trace = default_observability.active_traces.get(state.trace_id)
        latency = trace.total_duration_ms if trace else 0.0
        guard_passed = trace.guardrails_passed if trace else True
        agents = [t.agent_name for t in state.agent_traces]

        return EvaluationResponse(
            verdict=state.final_verdict,
            trace_id=state.trace_id,
            total_latency_ms=round(latency, 2),
            guardrails_passed=guard_passed,
            agents_executed=agents
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/traces")
def list_traces():
    return default_observability.list_traces()


@app.get("/traces/{trace_id}")
def get_trace_detail(trace_id: str):
    trace = default_observability.active_traces.get(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace ID not found")
    
    a2a_messages = [m.model_dump() for m in default_a2a_bus.get_trace_messages(trace_id)]
    return {
        "trace": trace.model_dump(),
        "a2a_messages": a2a_messages
    }


@app.get("/benchmark")
def get_benchmark():
    bench_file = os.path.join(PROJECT_ROOT, "evaluation", "benchmark_results.json")
    if os.path.exists(bench_file):
        import json
        with open(bench_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"message": "Benchmark has not been run yet."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)

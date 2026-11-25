"""
FinGuard Observability, Provenance, and Tracing System.
Implements Requirement 9:
- Open-source observability platform (Langfuse-compatible trace schema & direct API sync)
- Granular span tracking, token accounting, execution latency, and financial cost estimation
- End-to-end auditability and provenance for multi-agent workflows
"""

import os
import json
import uuid
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

TRACE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "traces")
os.makedirs(TRACE_DIR, exist_ok=True)

# Pricing model (Gemini 1.5 Flash reference rate: $0.075 per 1M input, $0.30 per 1M output)
COST_PER_MILLION_INPUT = 0.075
COST_PER_MILLION_OUTPUT = 0.30


class ObservabilitySpan(BaseModel):
    span_id: str = Field(default_factory=lambda: f"span_{uuid.uuid4().hex[:8]}")
    name: str
    agent_name: str
    framework: str  # ADK, CrewAI, MCP, Guardrail
    start_time: str
    end_time: Optional[str] = None
    duration_ms: float = 0.0
    status: str = "SUCCESS"  # SUCCESS, ERROR, BLOCKED
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
    mcp_tools_invoked: List[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error: Optional[str] = None


class FinGuardTrace(BaseModel):
    trace_id: str
    session_id: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    query: str
    purchase_amount: float
    category: str
    verdict: str = "PENDING"
    total_duration_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    spans: List[ObservabilitySpan] = Field(default_factory=list)
    guardrails_passed: bool = True
    frameworks_used: List[str] = Field(default_factory=lambda: ["ADK", "CrewAI", "MCP"])


class FinGuardObservability:
    """
    Observability logger tracking provenance, latency, tokens, and cost.
    Syncs with Langfuse API if configured, otherwise stores local trace graph.
    """
    def __init__(self):
        self.active_traces: Dict[str, FinGuardTrace] = {}
        self.langfuse_client = None
        self._init_langfuse()

    def _init_langfuse(self):
        """Attempt initialization of Langfuse if credentials present."""
        pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
        sk = os.environ.get("LANGFUSE_SECRET_KEY")
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        if pk and sk:
            try:
                import langfuse
                self.langfuse_client = langfuse.Langfuse(public_key=pk, secret_key=sk, host=host)
            except Exception:
                self.langfuse_client = None

    def start_trace(self, trace_id: str, session_id: str, query: str, purchase_amount: float, category: str) -> FinGuardTrace:
        trace = FinGuardTrace(
            trace_id=trace_id,
            session_id=session_id,
            query=query,
            purchase_amount=purchase_amount,
            category=category
        )
        self.active_traces[trace_id] = trace
        return trace

    def start_span(self, trace_id: str, agent_name: str, framework: str, span_name: str, input_data: Optional[Dict[str, Any]] = None) -> ObservabilitySpan:
        span = ObservabilitySpan(
            name=span_name,
            agent_name=agent_name,
            framework=framework,
            start_time=datetime.utcnow().isoformat(),
            input_data=input_data or {}
        )
        if trace_id in self.active_traces:
            self.active_traces[trace_id].spans.append(span)
        return span

    def end_span(
        self,
        trace_id: str,
        span: ObservabilitySpan,
        output_data: Dict[str, Any],
        duration_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        mcp_tools: Optional[List[str]] = None,
        status: str = "SUCCESS",
        error: Optional[str] = None
    ):
        span.end_time = datetime.utcnow().isoformat()
        span.duration_ms = duration_ms
        span.output_data = output_data
        span.status = status
        span.error = error
        span.prompt_tokens = prompt_tokens
        span.completion_tokens = completion_tokens
        span.total_tokens = prompt_tokens + completion_tokens
        span.mcp_tools_invoked = mcp_tools or []

        # Calculate cost
        cost = (prompt_tokens / 1_000_000.0 * COST_PER_MILLION_INPUT) + \
               (completion_tokens / 1_000_000.0 * COST_PER_MILLION_OUTPUT)
        span.estimated_cost_usd = round(cost, 7)

    def finish_trace(self, trace_id: str, verdict: str, guardrails_passed: bool = True) -> FinGuardTrace:
        trace = self.active_traces.get(trace_id)
        if not trace:
            return None

        trace.verdict = verdict
        trace.guardrails_passed = guardrails_passed
        trace.total_duration_ms = sum(s.duration_ms for s in trace.spans)
        trace.total_prompt_tokens = sum(s.prompt_tokens for s in trace.spans)
        trace.total_completion_tokens = sum(s.completion_tokens for s in trace.spans)
        trace.total_tokens = trace.total_prompt_tokens + trace.total_completion_tokens
        trace.total_cost_usd = sum(s.estimated_cost_usd for s in trace.spans)

        # Save to disk
        self._persist_trace(trace)

        # Sync to Langfuse if enabled
        if self.langfuse_client:
            try:
                lf_trace = self.langfuse_client.trace(
                    id=trace.trace_id,
                    name=f"FinGuard: {trace.query}",
                    session_id=trace.session_id,
                    metadata={"verdict": trace.verdict, "cost": trace.total_cost_usd}
                )
                for s in trace.spans:
                    lf_trace.span(
                        name=f"[{s.framework}] {s.agent_name}",
                        start_time=datetime.fromisoformat(s.start_time),
                        metadata={"duration_ms": s.duration_ms, "tokens": s.total_tokens}
                    )
            except Exception:
                pass

        return trace

    def _persist_trace(self, trace: FinGuardTrace):
        file_path = os.path.join(TRACE_DIR, f"{trace.trace_id}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(trace.model_dump_json(indent=2))
        except Exception as e:
            print(f"Failed to persist trace: {e}")

    def list_traces(self) -> List[Dict[str, Any]]:
        traces = []
        if not os.path.exists(TRACE_DIR):
            return traces
        for fname in sorted(os.listdir(TRACE_DIR), reverse=True):
            if fname.endswith(".json"):
                fpath = os.path.join(TRACE_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        traces.append({
                            "trace_id": data.get("trace_id"),
                            "timestamp": data.get("timestamp"),
                            "query": data.get("query"),
                            "verdict": data.get("verdict"),
                            "total_duration_ms": data.get("total_duration_ms"),
                            "total_tokens": data.get("total_tokens"),
                            "total_cost_usd": data.get("total_cost_usd")
                        })
                except Exception:
                    continue
        return traces


# Global Singleton Observability Engine
default_observability = FinGuardObservability()

"""
FinGuard Callback System for Task Monitoring & Execution Flow Tracking.
Implements Requirement 5:
- Tracks intermediate agent outputs, tool executions, state transitions, and errors.
- Provides hooks for real-time UI streaming and transparency debugging.
"""

import time
import logging
from typing import Dict, Any, List, Optional, Callable
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger("FinGuard_Callbacks")


class CallbackEvent(BaseModel):
    event_type: str  # AGENT_START, AGENT_STEP, TOOL_START, TOOL_END, TOOL_ERROR, STATE_UPDATE, AGENT_FINISH, AGENT_ERROR
    agent_name: str
    framework: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[float] = None


class FinGuardCallbackHandler:
    """
    Observer & Callback Manager that monitors all 11 agents in real time.
    """
    def __init__(self):
        self.events: List[CallbackEvent] = []
        self._listeners: List[Callable[[CallbackEvent], None]] = []

    def register_listener(self, listener: Callable[[CallbackEvent], None]):
        """Register real-time event listeners (e.g. Streamlit UI event stream)."""
        self._listeners.append(listener)

    def _notify(self, event: CallbackEvent):
        self.events.append(event)
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error(f"Callback listener error: {e}")

    def on_agent_start(self, agent_name: str, framework: str, task_desc: str):
        msg = f"▶ [{framework}] Agent '{agent_name}' started task: {task_desc}"
        logger.info(msg)
        self._notify(CallbackEvent(
            event_type="AGENT_START",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details={"task_description": task_desc}
        ))

    def on_agent_step(self, agent_name: str, framework: str, step_name: str, details: Optional[Dict[str, Any]] = None):
        msg = f"  ↳ Step: {step_name}"
        logger.debug(f"[{agent_name}] {msg}")
        self._notify(CallbackEvent(
            event_type="AGENT_STEP",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details=details or {}
        ))

    def on_tool_start(self, agent_name: str, framework: str, tool_name: str, inputs: Dict[str, Any]):
        msg = f"  ⚙ Calling Tool '{tool_name}'"
        logger.info(f"[{agent_name}] {msg} with inputs: {inputs}")
        self._notify(CallbackEvent(
            event_type="TOOL_START",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details={"tool_name": tool_name, "inputs": inputs}
        ))

    def on_tool_end(self, agent_name: str, framework: str, tool_name: str, output: Any, duration_ms: float):
        msg = f"  ✓ Tool '{tool_name}' returned in {duration_ms:.1f}ms"
        logger.info(f"[{agent_name}] {msg}")
        self._notify(CallbackEvent(
            event_type="TOOL_END",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details={"tool_name": tool_name, "output_preview": str(output)[:300]},
            duration_ms=duration_ms
        ))

    def on_tool_error(self, agent_name: str, framework: str, tool_name: str, error: str):
        msg = f"  ✗ Tool '{tool_name}' failed: {error}"
        logger.error(f"[{agent_name}] {msg}")
        self._notify(CallbackEvent(
            event_type="TOOL_ERROR",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details={"tool_name": tool_name, "error": error}
        ))

    def on_state_update(self, agent_name: str, framework: str, field_updated: str, summary: str):
        msg = f"  🔄 Context Updated: '{field_updated}' -> {summary}"
        logger.info(f"[{agent_name}] {msg}")
        self._notify(CallbackEvent(
            event_type="STATE_UPDATE",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details={"field_updated": field_updated, "summary": summary}
        ))

    def on_agent_finish(self, agent_name: str, framework: str, result_summary: str, duration_ms: float):
        msg = f"✔ [{framework}] Agent '{agent_name}' finished in {duration_ms:.1f}ms. Output: {result_summary}"
        logger.info(msg)
        self._notify(CallbackEvent(
            event_type="AGENT_FINISH",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details={"summary": result_summary},
            duration_ms=duration_ms
        ))

    def on_agent_error(self, agent_name: str, framework: str, error_message: str):
        msg = f"❌ [{framework}] Agent '{agent_name}' encountered an error: {error_message}"
        logger.error(msg)
        self._notify(CallbackEvent(
            event_type="AGENT_ERROR",
            agent_name=agent_name,
            framework=framework,
            message=msg,
            details={"error": error_message}
        ))

    def clear(self):
        self.events.clear()


# Global Singleton Handler
default_callback_handler = FinGuardCallbackHandler()

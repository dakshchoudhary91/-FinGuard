
"""
CrewAI Base Architecture for FinGuard.

Responsibilities:
- Shared domain-service lifecycle
- MCP tool execution and result validation
- A2A messaging
- Callback monitoring
- Observability integration

Native CrewAI Agent, Task, LLM and Crew execution
are managed by agents/native_framework_runtime.py.
"""

import os
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Literal

from dotenv import load_dotenv

PROJECT_ROOT = Path(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
)

load_dotenv(PROJECT_ROOT / ".env", override=False)

# Keep CrewAI local storage within the project.
# Do not globally disable OpenTelemetry.
LOCAL_APPDATA = PROJECT_ROOT / "localappdata"

LOCAL_APPDATA.mkdir(
    parents=True,
    exist_ok=True
)

os.environ.setdefault(
    "LOCALAPPDATA",
    str(LOCAL_APPDATA)
)

os.environ.setdefault(
    "CREWAI_STORAGE_DIR",
    str(LOCAL_APPDATA / "crewai")
)

logger = logging.getLogger("FinGuard_CrewAI")


from core.state import FinGuardState

from core.protocol_a2a import (
    A2AMessage,
    A2AParty,
    default_a2a_bus
)

from core.callbacks import default_callback_handler
from core.observability import default_observability
from mcp_service.client import default_mcp_client
from core.guardrails import FinGuardGuardrails


class CrewAIDomainService:
    """
    Shared domain-service base for FinGuard CrewAI agents.

    Each subclass implements its own financial operations.
    Native CrewAI execution is managed separately by
    native_framework_runtime.py.
    """

    def __init__(
        self,
        agent_id: str,
        name: str,
        role: str,
        goal: str,
        backstory: str
    ):
        self.agent_id = agent_id
        self.name = name
        self.role = role
        self.goal = goal
        self.backstory = backstory

        self.party = A2AParty(
            agent_id=self.agent_id,
            framework="CrewAI",
            role=self.role
        )

        self.mcp = default_mcp_client
        self.callbacks = default_callback_handler
        self.observability = default_observability
        self.bus = default_a2a_bus

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute an MCP tool and validate its response.

        Invalid results are rejected to prevent unsafe or
        incorrect financial calculations.
        """

        if not isinstance(arguments, dict):
            raise TypeError(
                f"MCP arguments for {tool_name} must be a dictionary."
            )

        start_time = time.perf_counter()

        self.callbacks.on_tool_start(
            self.name,
            "CrewAI",
            tool_name,
            arguments
        )

        try:
            result = self.mcp.call_tool(
                tool_name,
                arguments
            )

            if not isinstance(result, dict):
                raise TypeError(
                    f"MCP tool '{tool_name}' returned "
                    f"{type(result).__name__}; expected dict."
                )

            valid, error = FinGuardGuardrails.validate_tool_output(
                tool_name,
                result
            )

            if not valid:
                raise ValueError(
                    f"MCP output validation failed for "
                    f"'{tool_name}': {error}"
                )

            duration_ms = (
                time.perf_counter() - start_time
            ) * 1000

            self.callbacks.on_tool_end(
                self.name,
                "CrewAI",
                tool_name,
                result,
                duration_ms
            )

            return result

        except Exception as exc:
            duration_ms = (
                time.perf_counter() - start_time
            ) * 1000

            logger.exception(
                "CrewAI MCP tool execution failed: %s",
                tool_name
            )

            self.callbacks.on_tool_error(
                self.name,
                "CrewAI",
                tool_name,
                str(exc)
            )

            raise

    def send_a2a_message(
        self,
        recipient_id: str,
        recipient_framework: Literal["ADK", "CrewAI", "SYSTEM"],
        recipient_role: str,
        topic: str,
        content: Dict[str, Any],
        trace_id: str,
        performative: Literal[
            "INFORM",
            "REQUEST",
            "PROPOSE",
            "ALERT",
            "QUERY",
            "CONFIRM"
        ] = "INFORM",
        state_delta: Optional[Dict[str, Any]] = None
    ) -> A2AMessage:
        """
        Send a standardized A2A message through the shared bus.

        The destination agent must register a subscriber to
        receive and process the message.
        """

        if not recipient_id or not trace_id or not topic:
            raise ValueError(
                "A2A recipient_id, trace_id and topic are required."
            )

        if not isinstance(content, dict):
            raise TypeError("A2A content must be a dictionary.")

        message = A2AMessage(
            trace_id=trace_id,
            sender=self.party,
            recipient=A2AParty(
                agent_id=recipient_id,
                framework=recipient_framework,
                role=recipient_role
            ),
            performative=performative,
            topic=topic,
            content=content,
            state_delta=state_delta
        )

        try:
            self.bus.dispatch(message)

            logger.info(
                "A2A message dispatched: %s",
                message.summary()
            )

            return message

        except Exception:
            logger.exception(
                "A2A dispatch failed: %s",
                message.message_id
            )
            raise

    def run(self, state: FinGuardState) -> FinGuardState:
        """
        Subclasses implement their own domain-specific logic.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run()."
        )

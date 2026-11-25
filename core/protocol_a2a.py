
"""
FinGuard Agent-to-Agent (A2A) Communication Protocol.

Provides:
- Cross-framework ADK and CrewAI communication
- Standardized Pydantic message envelopes
- Recipient-based message routing
- Thread-safe subscriptions and dispatch
- Delivery status and error tracking
- Trace-based message history
"""

import logging
import threading
import uuid

from datetime import datetime, timezone
from typing import (
    Dict,
    Any,
    List,
    Optional,
    Callable,
    Literal,
)

from pydantic import BaseModel, Field


logger = logging.getLogger("FinGuard_A2A")


class A2AParty(BaseModel):
    """Identity of an agent participating in A2A communication."""

    agent_id: str
    framework: Literal["ADK", "CrewAI", "SYSTEM"]
    role: str


class A2AMessage(BaseModel):
    """Standardized A2A message envelope."""

    protocol: str = "A2A/1.0"

    message_id: str = Field(
        default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}"
    )

    trace_id: str

    timestamp: str = Field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )

    sender: A2AParty
    recipient: A2AParty

    performative: Literal[
        "INFORM",
        "REQUEST",
        "PROPOSE",
        "ALERT",
        "QUERY",
        "CONFIRM",
    ]

    topic: str
    content: Dict[str, Any]
    state_delta: Optional[Dict[str, Any]] = None

    def summary(self) -> str:
        return (
            f"[{self.protocol}] "
            f"{self.sender.agent_id} ({self.sender.framework}) -> "
            f"{self.recipient.agent_id} ({self.recipient.framework}) | "
            f"{self.performative} [{self.topic}]"
        )


class A2AMessageBus:
    """
    Thread-safe communication bus for ADK and CrewAI agents.

    A message is delivered only when its recipient has registered
    a subscriber. Every dispatch produces a delivery report.
    """

    def __init__(self):
        self.message_history: List[A2AMessage] = []

        self._subscribers: Dict[
            str,
            List[Callable[[A2AMessage], None]]
        ] = {}

        self._global_listeners: List[
            Callable[[A2AMessage], None]
        ] = []

        self._delivery_reports: Dict[str, Dict[str, Any]] = {}
        self._dispatched_ids = set()

        self._lock = threading.RLock()

    def subscribe(
        self,
        agent_id: str,
        handler: Callable[[A2AMessage], None],
    ) -> bool:
        """
        Register a recipient handler.

        Returns False if the same handler is already registered.
        """

        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("A2A subscriber agent_id cannot be empty.")

        if not callable(handler):
            raise TypeError("A2A subscriber handler must be callable.")

        with self._lock:
            handlers = self._subscribers.setdefault(agent_id, [])

            if handler in handlers:
                return False

            handlers.append(handler)

            logger.info(
                "A2A subscriber registered: %s",
                agent_id,
            )

            return True

    def unsubscribe(
        self,
        agent_id: str,
        handler: Optional[Callable[[A2AMessage], None]] = None,
    ) -> bool:
        """
        Remove one handler or all handlers for an agent.

        Returns True when a subscription was removed.
        """

        with self._lock:
            if agent_id not in self._subscribers:
                return False

            if handler is None:
                del self._subscribers[agent_id]
                return True

            handlers = self._subscribers[agent_id]

            if handler not in handlers:
                return False

            handlers.remove(handler)

            if not handlers:
                del self._subscribers[agent_id]

            return True

    def add_global_listener(
        self,
        listener: Callable[[A2AMessage], None],
    ) -> bool:
        """Register an audit, logging or tracing listener."""

        if not callable(listener):
            raise TypeError("Global listener must be callable.")

        with self._lock:
            if listener in self._global_listeners:
                return False

            self._global_listeners.append(listener)
            return True

    def remove_global_listener(
        self,
        listener: Callable[[A2AMessage], None],
    ) -> bool:
        """Remove a previously registered global listener."""

        with self._lock:
            if listener not in self._global_listeners:
                return False

            self._global_listeners.remove(listener)
            return True

    def dispatch(
        self,
        message: A2AMessage,
    ) -> Dict[str, Any]:
        """
        Record and deliver a message.

        Delivery statuses:
        - delivered
        - partially_delivered
        - delivery_failed
        - no_subscriber
        - duplicate

        Handler exceptions are captured in the delivery report.
        """

        if not isinstance(message, A2AMessage):
            raise TypeError("dispatch() requires an A2AMessage.")

        with self._lock:

            if message.message_id in self._dispatched_ids:
                logger.warning(
                    "Duplicate A2A message rejected: %s",
                    message.message_id,
                )

                return {
                    "message_id": message.message_id,
                    "status": "duplicate",
                    "delivered_to": [],
                    "errors": [],
                }

            self._dispatched_ids.add(message.message_id)
            self.message_history.append(message)

            recipient_id = message.recipient.agent_id

            handlers = list(
                self._subscribers.get(recipient_id, [])
            )

            global_listeners = list(self._global_listeners)

        listener_errors = []

        # Notify audit and observability listeners.
        for listener in global_listeners:
            try:
                listener(message)

            except Exception as exc:
                listener_errors.append(str(exc))

                logger.exception(
                    "A2A global listener failed for message %s",
                    message.message_id,
                )

        delivered_to = []
        delivery_errors = []

        # Deliver to the intended recipient.
        for index, handler in enumerate(handlers):

            try:
                handler(message)

                delivered_to.append({
                    "agent_id": recipient_id,
                    "handler_index": index,
                })

            except Exception as exc:
                delivery_errors.append({
                    "agent_id": recipient_id,
                    "handler_index": index,
                    "error": str(exc),
                })

                logger.exception(
                    "A2A delivery failed for recipient %s",
                    recipient_id,
                )

        # Determine actual delivery status.
        if not handlers:
            status = "no_subscriber"

        elif delivery_errors and delivered_to:
            status = "partially_delivered"

        elif delivery_errors:
            status = "delivery_failed"

        else:
            status = "delivered"

        report = {
            "message_id": message.message_id,
            "trace_id": message.trace_id,
            "sender": message.sender.agent_id,
            "recipient": recipient_id,
            "topic": message.topic,
            "status": status,
            "handlers_registered": len(handlers),
            "delivered_to": delivered_to,
            "errors": delivery_errors,
            "listener_errors": listener_errors,
        }

        with self._lock:
            self._delivery_reports[message.message_id] = report

        if status == "no_subscriber":
            logger.warning(
                "A2A message %s was recorded but NOT delivered. "
                "No subscriber registered for '%s'.",
                message.message_id,
                recipient_id,
            )

        else:
            logger.info(
                "A2A message delivery: %s -> %s | status=%s",
                message.sender.agent_id,
                recipient_id,
                status,
            )

        return report

    def get_delivery_report(
        self,
        message_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the delivery report for a message."""

        with self._lock:
            report = self._delivery_reports.get(message_id)

            return dict(report) if report else None

    def get_trace_messages(
        self,
        trace_id: str,
    ) -> List[A2AMessage]:
        """Retrieve all messages belonging to a trace."""

        with self._lock:
            return [
                message
                for message in self.message_history
                if message.trace_id == trace_id
            ]

    def get_subscribers(self) -> List[str]:
        """Return registered recipient agent IDs."""

        with self._lock:
            return list(self._subscribers.keys())

    def get_statistics(self) -> Dict[str, Any]:
        """Return message bus delivery statistics."""

        with self._lock:
            reports = list(self._delivery_reports.values())

            counts = {
                "delivered": 0,
                "partially_delivered": 0,
                "delivery_failed": 0,
                "no_subscriber": 0,
            }

            for report in reports:
                status = report["status"]

                if status in counts:
                    counts[status] += 1

            return {
                "total_messages": len(self.message_history),
                "registered_agents": len(self._subscribers),
                "total_subscriptions": sum(
                    len(handlers)
                    for handlers in self._subscribers.values()
                ),
                "delivery_status_counts": counts,
            }

    def clear(self):
        """
        Clear message history and delivery reports.

        Subscriptions and global listeners are preserved.
        """

        with self._lock:
            self.message_history.clear()
            self._delivery_reports.clear()
            self._dispatched_ids.clear()


# Shared singleton bus used by ADK and CrewAI agents.
default_a2a_bus = A2AMessageBus()

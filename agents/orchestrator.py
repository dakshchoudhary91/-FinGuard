
"""Master FinGuard Orchestrator with phase-level diagnostics."""

import logging
import os
import time
from collections import deque
from typing import Sequence, Any

from agents.native_framework_runtime import (
    run_native_adk_batch,
    run_native_crewai_batch
)

from core.state import FinGuardState, PurchaseRequest, FinGuardVerdict
from core.guardrails import FinGuardGuardrails
from core.protocol_a2a import default_a2a_bus
from core.callbacks import default_callback_handler
from core.observability import default_observability

from agents.adk_framework.checking_watcher import CheckingWatcherAgent
from agents.adk_framework.credit_card_watcher import CreditCardWatcherAgent
from agents.adk_framework.savings_watcher import SavingsWatcherAgent
from agents.adk_framework.investment_watcher import InvestmentWatcherAgent
from agents.adk_framework.risk_anomaly import RiskAnomalyAgent
from agents.adk_framework.coordinator import CoordinatorAgent

from agents.crewai_framework.bill_analysis import BillAnalysisAgent
from agents.crewai_framework.budget_analysis import BudgetAnalysisAgent
from agents.crewai_framework.cash_flow_forecast import CashFlowForecastAgent
from agents.crewai_framework.goal_progress import GoalProgressAgent
from agents.crewai_framework.affordability_evaluator import AffordabilityEvaluatorAgent

logger = logging.getLogger("FinGuard_Orchestrator")


class FinGuardOrchestrator:

    def __init__(self):
        self.checking_watcher = CheckingWatcherAgent()
        self.credit_card_watcher = CreditCardWatcherAgent()
        self.savings_watcher = SavingsWatcherAgent()
        self.investment_watcher = InvestmentWatcherAgent()

        self.risk_anomaly = RiskAnomalyAgent()
        self.coordinator = CoordinatorAgent()

        self.bill_analysis = BillAnalysisAgent()
        self.budget_analysis = BudgetAnalysisAgent()
        self.cash_flow_forecast = CashFlowForecastAgent()
        self.goal_progress = GoalProgressAgent()
        self.affordability_evaluator = AffordabilityEvaluatorAgent()

        self.bus = default_a2a_bus
        self.callbacks = default_callback_handler
        self.observability = default_observability

        # Every agent registers as an A2A recipient so cross-framework
        # messages (ADK <-> CrewAI) are actually delivered, not just logged.
        self.a2a_inboxes = {}
        for service in (
            self.checking_watcher, self.credit_card_watcher,
            self.savings_watcher, self.investment_watcher,
            self.risk_anomaly, self.coordinator,
            self.bill_analysis, self.budget_analysis,
            self.cash_flow_forecast, self.goal_progress,
            self.affordability_evaluator,
        ):
            self._register_a2a_inbox(service.agent_id)

    def _register_a2a_inbox(self, agent_id):
        inbox = self.a2a_inboxes.setdefault(
            agent_id, deque(maxlen=50)
        )
        self.bus.subscribe(agent_id, inbox.append)

    @staticmethod
    def _native_enabled():
        return os.getenv(
            "FINGUARD_NATIVE_FRAMEWORKS", "false"
        ).strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def _log(message):
        print(f"\n[FinGuard] {message}", flush=True)

    def _execute_phase(self, phase_name, services, state, framework, native):
        names = ", ".join(service.name for service in services)
        start = time.time()

        self._log(
            f"STARTED: {phase_name} | Framework: {framework} | Agents: {names}"
        )

        try:
            if native:
                if framework == "ADK":
                    state = run_native_adk_batch(services, state)
                else:
                    state = run_native_crewai_batch(services, state)
            else:
                for service in services:
                    self._log(f"Running offline service: {service.name}")
                    state = service.run(state)

            duration = time.time() - start

            self._log(
                f"COMPLETED: {phase_name} | Duration: {duration:.2f}s"
            )

            return state

        except Exception as exc:
            duration = time.time() - start

            self._log(
                f"FAILED: {phase_name} after {duration:.2f}s | "
                f"{type(exc).__name__}: {exc}"
            )

            logger.exception("Failure in %s", phase_name)
            raise

    def evaluate_purchase(
        self,
        item_name: str,
        amount: float,
        category: str = "Shopping & Discretionary",
        urgency: str = "low",
        notes: str = "",
        session_id: str = "user_default"
    ):

        state = FinGuardState(
            session_id=session_id,
            purchase_request=PurchaseRequest(
                item_name=item_name,
                amount=amount,
                category=category,
                urgency=urgency,
                notes=notes
            )
        )

        self.observability.start_trace(
            trace_id=state.trace_id,
            session_id=session_id,
            query=f"Can I afford {item_name} for ${amount:,.2f}?",
            purchase_amount=amount,
            category=category
        )

        # Input guardrails
        guard_start = time.time()

        is_valid, guard_reason = FinGuardGuardrails.validate_user_input(
            item_name, amount
        )

        guard_span = self.observability.start_span(
            state.trace_id,
            "InputGuardrail",
            "Guardrail",
            "validate_user_prompt"
        )

        if not is_valid:
            duration = (time.time() - guard_start) * 1000

            self.callbacks.on_agent_error(
                "InputGuardrail", "Guardrail", guard_reason
            )

            self.observability.end_span(
                state.trace_id,
                guard_span,
                {"status": "BLOCKED", "reason": guard_reason},
                duration,
                status="BLOCKED",
                error=guard_reason
            )

            state.add_trace(
                "InputGuardrail",
                "Guardrail",
                "Prompt Security Check",
                "BLOCKED",
                item_name,
                guard_reason,
                duration
            )

            state.final_verdict = FinGuardVerdict(
                item_name=item_name,
                amount=amount,
                category=category,
                verdict="CRITICAL_DEFICIT",
                verdict_badge_color="#6c757d",
                confidence_score=1.0,
                headline="Security Policy Enforcement: Request Blocked",
                executive_summary=(
                    f"The system blocked this request: {guard_reason}"
                ),
                critical_warnings=[f"SECURITY ALERT: {guard_reason}"],
                actionable_alternatives=[
                    "Rephrase your request using legitimate financial terms."
                ],
                provenance_trace_id=state.trace_id
            )

            self.observability.finish_trace(
                state.trace_id, "BLOCKED", guardrails_passed=False
            )

            return state

        self.observability.end_span(
            state.trace_id,
            guard_span,
            {"status": "PASSED"},
            (time.time() - guard_start) * 1000
        )

        native = self._native_enabled()

        self._log(
            f"PURCHASE STARTED | Item: {item_name} | Amount: ${amount:.2f}"
        )
        self._log(f"Native framework mode: {native}")

        try:
            # Phase 1: Four ADK account watchers
            state = self._execute_phase(
                "PHASE 1 - Account Watchers",
                [
                    self.checking_watcher,
                    self.credit_card_watcher,
                    self.savings_watcher,
                    self.investment_watcher
                ],
                state, "ADK", native
            )

            # Phase 2: Four CrewAI financial analysts
            state = self._execute_phase(
                "PHASE 2 - Financial Analysis",
                [
                    self.bill_analysis,
                    self.budget_analysis,
                    self.cash_flow_forecast,
                    self.goal_progress
                ],
                state, "CrewAI", native
            )

            # Phase 3: ADK risk assessment
            state = self._execute_phase(
                "PHASE 3 - Risk and Anomaly",
                [self.risk_anomaly],
                state, "ADK", native
            )

            # Phase 4: CrewAI affordability
            state = self._execute_phase(
                "PHASE 4 - Affordability Evaluation",
                [self.affordability_evaluator],
                state, "CrewAI", native
            )

            # Phase 5: ADK coordinator
            state = self._execute_phase(
                "PHASE 5 - Final Coordination",
                [self.coordinator],
                state, "ADK", native
            )

            verdict = (
                state.final_verdict.verdict
                if state.final_verdict
                else "UNKNOWN"
            )

            self.observability.finish_trace(
                state.trace_id,
                verdict,
                guardrails_passed=True
            )

            self._log(f"PIPELINE COMPLETED | Final verdict: {verdict}")

            return state

        except Exception as exc:
            self._log(
                f"PIPELINE FAILED | {type(exc).__name__}: {exc}"
            )

            try:
                self.observability.finish_trace(
                    state.trace_id,
                    "ERROR",
                    guardrails_passed=True
                )
            except Exception:
                logger.exception("Could not finish observability trace")

            raise RuntimeError(
                f"FinGuard failed: {type(exc).__name__}: {exc}"
            ) from exc


default_orchestrator = FinGuardOrchestrator()

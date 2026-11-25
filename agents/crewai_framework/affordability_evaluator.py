
"""
Agent 11: Affordability Evaluator Agent (CrewAI Framework).

Evaluates purchase affordability using:
- Available checking balance
- Overdue and upcoming bills
- Emergency reserve status
- Category budget status
- Projected cash-flow trajectory
- MCP affordability calculations
"""

import logging
import math
import time

from agents.crewai_framework.crew_bridge import CrewAIDomainService
from core.state import FinGuardState, AffordabilityEvaluationState


logger = logging.getLogger("FinGuard_Affordability")


class AffordabilityEvaluatorAgent(CrewAIDomainService):

    def __init__(self):
        super().__init__(
            agent_id="crewai_affordability",
            name="Affordability Evaluator Agent",
            role="Discretionary Underwriter & Purchasing Decision Engine",
            goal=(
                "Evaluate purchase affordability using verified liquidity, "
                "outstanding obligations, budget status, and reserve risks."
            ),
            backstory=(
                "A deterministic financial underwriter that evaluates "
                "purchase decisions using available financial evidence. "
                "It does not assume missing financial information is safe."
            )
        )

    @staticmethod
    def _valid_number(value, field_name):
        """Convert a value to a finite monetary or ratio number."""
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be numeric.")

        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be numeric.")

        if not math.isfinite(result):
            raise ValueError(f"{field_name} must be finite.")

        return result

    def run(self, state: FinGuardState) -> FinGuardState:
        t0 = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "CrewAI",
            "Evaluating purchase against liquidity, bills, budget, and reserves"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "CrewAI",
            "evaluate_affordability"
        )

        try:
            # --------------------------------------------------
            # 1. Read and validate shared financial state
            # --------------------------------------------------
            request = state.purchase_request
            checking = state.checking
            bills = state.bill_analysis
            budget = state.budget_analysis
            cash_flow = state.cash_flow
            goals = state.goal_progress

            purchase_amount = self._valid_number(
                request.amount,
                "Purchase amount"
            )

            checking_balance = self._valid_number(
                checking.available_balance,
                "Available checking balance"
            )

            overdue_bills = self._valid_number(
                bills.total_overdue_bills,
                "Overdue bills"
            )

            upcoming_bills_7d = self._valid_number(
                bills.total_upcoming_bills_7d,
                "Upcoming 7-day bills"
            )

            next_bill_amount = self._valid_number(
                bills.next_major_bill_amount,
                "Next major bill amount"
            )

            next_bill_days = int(
                bills.days_to_next_major_bill
            )

            if any(value < 0 for value in (
                purchase_amount,
                checking_balance,
                overdue_bills,
                upcoming_bills_7d,
                next_bill_amount
            )):
                raise ValueError(
                    "Purchase, balance, and bill amounts cannot be negative."
                )

            # --------------------------------------------------
            # 2. MCP affordability calculation
            # --------------------------------------------------
            afford_result = self.call_mcp_tool(
                "financial_calculator",
                {
                    "calc_type": "affordability_ratio",
                    "liquid_cash": checking_balance,
                    "purchase_amount": purchase_amount
                }
            )

            if not isinstance(afford_result, dict):
                raise ValueError(
                    "MCP affordability calculator returned invalid data."
                )

            ratio = self._valid_number(
                afford_result.get("liquidity_retention_ratio"),
                "Liquidity retention ratio"
            )

            remaining_cash = self._valid_number(
                afford_result.get("remaining_cash"),
                "Remaining cash"
            )

            if not 0.0 <= ratio <= 1.0:
                raise ValueError(
                    "MCP returned a liquidity retention ratio outside 0-1."
                )

            # Cross-check MCP output against the direct calculation.
            expected_remaining = checking_balance - purchase_amount

            if abs(remaining_cash - expected_remaining) > 0.02:
                raise ValueError(
                    "MCP remaining cash does not match the "
                    "checking balance minus purchase amount."
                )

            # --------------------------------------------------
            # 3. Calculate obligations after the purchase
            # --------------------------------------------------
            total_7d_obligations = (
                overdue_bills + upcoming_bills_7d
            )

            projected_after_obligations = (
                remaining_cash - total_7d_obligations
            )

            overdraft_risk = bool(
                cash_flow.will_trigger_overdraft
                or projected_after_obligations < 0
            )

            # --------------------------------------------------
            # 4. Determine budget data reliability
            # --------------------------------------------------
            budget_status = str(
                budget.category_status or "UNKNOWN"
            ).upper()

            budget_unavailable_statuses = {
                "STALE_BUDGET",
                "UNKNOWN_CATEGORY",
                "UNKNOWN",
                "NORMAL",
                "NO_BUDGET"
            }

            budget_available = (
                budget_status not in budget_unavailable_statuses
            )

            budget_exceeded = bool(
                budget.exceeds_budget_if_purchased
            )

            budget_overage = self._valid_number(
                budget.projected_overage_amount,
                "Projected budget overage"
            )

            # --------------------------------------------------
            # 5. Evaluate emergency reserve status
            # --------------------------------------------------
            reserve_breached = bool(
                goals.violates_emergency_reserve_floor
            )

            # --------------------------------------------------
            # 6. Determine affordability verdict
            # --------------------------------------------------
            verdict = "CAN_AFFORD"
            reason = ""
            confidence = 0.95

            # CASE A: Purchase exceeds available checking cash.
            if remaining_cash < 0:
                verdict = "CRITICAL_DEFICIT"
                confidence = 0.99

                reason = (
                    f"The purchase costs ${purchase_amount:,.2f}, "
                    f"but available checking balance is only "
                    f"${checking_balance:,.2f}. "
                    f"The resulting balance would be "
                    f"${remaining_cash:,.2f}."
                )

            # CASE B: Purchase leaves insufficient money for obligations.
            elif projected_after_obligations < 0:
                verdict = "CANNOT_AFFORD"
                confidence = 0.99

                reason = (
                    f"After the purchase, overdue bills of "
                    f"${overdue_bills:,.2f} and upcoming 7-day "
                    f"obligations of ${upcoming_bills_7d:,.2f} "
                    f"would leave a projected shortfall of "
                    f"${abs(projected_after_obligations):,.2f}."
                )

            # CASE C: An identified major bill is imminent or overdue.
            elif (
                next_bill_amount > 0
                and next_bill_days <= 5
                and remaining_cash < next_bill_amount
            ):
                verdict = "CANNOT_AFFORD"
                confidence = 0.98

                if next_bill_days < 0:
                    due_description = (
                        f"overdue by {abs(next_bill_days)} days"
                    )
                elif next_bill_days == 0:
                    due_description = "due today"
                else:
                    due_description = (
                        f"due in {next_bill_days} days"
                    )

                reason = (
                    f"The purchase would leave ${remaining_cash:,.2f}, "
                    f"which is insufficient for "
                    f"{bills.next_major_bill_name} "
                    f"(${next_bill_amount:,.2f}), {due_description}."
                )

            # CASE D: Emergency reserve floor is breached.
            elif reserve_breached:
                verdict = "CANNOT_AFFORD"
                confidence = 0.97

                reason = (
                    "The purchase conflicts with the emergency "
                    "reserve floor recorded in the financial goal state."
                )

            # CASE E: Budget figures cannot be trusted.
            elif not budget_available:
                verdict = "CONDITIONAL_AFFORD"
                confidence = 0.70

                reason = (
                    f"Immediate checking liquidity is sufficient, "
                    f"but the category budget cannot be verified "
                    f"(budget status: {budget_status}). "
                    "Update the budget data before treating this "
                    "purchase as fully affordable."
                )

            # CASE F: Purchase exceeds the category budget.
            elif budget_exceeded:
                verdict = "CONDITIONAL_AFFORD"
                confidence = 0.90

                reason = (
                    f"The purchase would exceed the "
                    f"{budget.category} budget by "
                    f"${budget_overage:,.2f}. "
                    "Checking liquidity alone does not make "
                    "the purchase budget-compliant."
                )

            # CASE G: Cash-flow trajectory indicates tight liquidity.
            elif str(
                cash_flow.cash_flow_trajectory
            ).upper() in {"TIGHT", "NEGATIVE", "SEVERE_DEFICIT"}:
                verdict = "CONDITIONAL_AFFORD"
                confidence = 0.90

                reason = (
                    f"The purchase leaves ${remaining_cash:,.2f} "
                    f"after purchase, but the cash-flow forecast "
                    f"reports {cash_flow.cash_flow_trajectory}. "
                    f"Projected balance after recorded obligations: "
                    f"${projected_after_obligations:,.2f}."
                )

            # CASE H: Budget exhausted by the purchase.
            elif budget_status == "BUDGET_EXHAUSTED":
                verdict = "CONDITIONAL_AFFORD"
                confidence = 0.90

                reason = (
                    f"The purchase would consume the remaining "
                    f"${budget.remaining_budget:,.2f} category budget."
                )

            # CASE I: All available checks pass.
            else:
                verdict = "CAN_AFFORD"
                confidence = 0.95

                reason = (
                    f"The purchase leaves ${remaining_cash:,.2f} "
                    f"after purchase and ${projected_after_obligations:,.2f} "
                    f"after recorded overdue and 7-day obligations. "
                    f"Liquidity retention is {ratio * 100:.1f}%, "
                    "and the available budget and reserve checks pass."
                )

            # Confidence is a rule-based indicator, not a calibrated
            # statistical probability.
            stress_passed = verdict == "CAN_AFFORD"

            # --------------------------------------------------
            # 7. Update Pydantic state
            # --------------------------------------------------
            state.affordability = AffordabilityEvaluationState(
                verdict=verdict,
                confidence_score=confidence,
                primary_reason=reason,
                affordability_ratio=round(ratio, 4),
                stress_test_passed=stress_passed
            )

            # --------------------------------------------------
            # 8. Send A2A underwriting decision to coordinator
            # --------------------------------------------------
            self.send_a2a_message(
                recipient_id="adk_coordinator",
                recipient_framework="ADK",
                recipient_role="Coordinator Synthesizer",
                topic="affordability_underwriting_decision",
                content={
                    "verdict": verdict,
                    "confidence_score": confidence,
                    "confidence_type": "rule_based_not_calibrated_probability",
                    "primary_reason": reason,
                    "affordability_ratio": ratio,
                    "stress_test_passed": stress_passed,
                    "remaining_cash": remaining_cash,
                    "overdue_bills": overdue_bills,
                    "upcoming_bills_7d": upcoming_bills_7d,
                    "projected_after_obligations": (
                        projected_after_obligations
                    ),
                    "budget_available": budget_available,
                    "budget_status": budget_status,
                    "budget_exceeded": budget_exceeded,
                    "reserve_breached": reserve_breached
                },
                trace_id=state.trace_id,
                state_delta={
                    "underwriting_verdict": verdict
                }
            )

            # --------------------------------------------------
            # 9. Record execution
            # --------------------------------------------------
            duration_ms = (time.time() - t0) * 1000.0

            summary = (
                f"Verdict: {verdict} | "
                f"Confidence indicator: {confidence:.2f} | "
                f"Liquidity retention: {ratio * 100:.1f}% | "
                f"After obligations: ${projected_after_obligations:,.2f} | "
                f"Budget status: {budget_status} | "
                f"Stress checks passed: {stress_passed}"
            )

            self.callbacks.on_state_update(
                self.name,
                "CrewAI",
                "state.affordability",
                summary
            )

            self.callbacks.on_agent_finish(
                self.name,
                "CrewAI",
                summary,
                duration_ms
            )

            self.observability.end_span(
                state.trace_id,
                span,
                {
                    "affordability": state.affordability.model_dump(),
                    "budget_available": budget_available,
                    "projected_after_obligations": (
                        projected_after_obligations
                    )
                },
                duration_ms,
                mcp_tools=["financial_calculator"]
            )

            state.add_trace(
                self.name,
                "CrewAI",
                "Underwriting Decision Calculation",
                "SUCCESS",
                "Evaluated affordability against available financial evidence",
                summary,
                duration_ms
            )

            return state

        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000.0

            logger.exception(
                "Affordability evaluation failed."
            )

            self.callbacks.on_agent_finish(
                self.name,
                "CrewAI",
                f"FAILED: {exc}",
                duration_ms
            )

            self.observability.end_span(
                state.trace_id,
                span,
                {"error": str(exc)},
                duration_ms
            )

            state.add_trace(
                self.name,
                "CrewAI",
                "Underwriting Decision Calculation",
                "ERROR",
                "Affordability evaluation failed",
                str(exc),
                duration_ms
            )

            raise

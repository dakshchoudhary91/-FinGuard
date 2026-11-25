
"""
Agent 6: Coordinator Agent (Google ADK Framework).

Synthesizes findings from the ten domain agents, applies final
financial safety checks, and creates the structured FinGuardVerdict.
"""

import logging
import math
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from agents.adk_framework.base import ADKDomainService
from core.state import (
    FinGuardState,
    FinGuardVerdict,
    FinancialMetricRow,
    TimelineCashEvent,
)
from core.guardrails import FinGuardGuardrails

logger = logging.getLogger("FinGuard_Coordinator")


class CoordinatorAgent(ADKDomainService):
    def __init__(self):
        super().__init__(
            agent_id="adk_coordinator",
            name="Coordinator Agent",
            role="Chief Financial Decision Synthesizer",
            instructions=(
                "Synthesize findings from all FinGuard agents. "
                "Apply financial safety rules, distinguish confirmed "
                "facts from projections, and produce a structured "
                "purchase recommendation."
            ),
        )

    @staticmethod
    def _number(value: Any, field_name: str) -> float:
        """Convert a value into a finite floating-point number."""
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{field_name} must be a valid number."
            )

        if not math.isfinite(result):
            raise ValueError(
                f"{field_name} must be finite."
            )

        return result

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        """Parse a date from an ISO date or datetime string."""
        if not value:
            return None

        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _unique_append(
        collection: List[str],
        message: str,
    ) -> None:
        if message and message not in collection:
            collection.append(message)

    def _build_cash_timeline(
        self,
        state: FinGuardState,
        today: date,
    ) -> Tuple[List[TimelineCashEvent], float]:
        """
        Build a 14-day projected timeline from actual bill records.

        Only mandatory, unpaid bills with valid due dates are included.
        Overdue bills are shown as due today, with their overdue status
        retained in the event description.
        """
        checking = self._number(
            state.checking.available_balance,
            "checking.available_balance",
        )
        purchase = self._number(
            state.purchase_request.amount,
            "purchase_request.amount",
        )

        current_balance = checking - purchase

        events = [
            {
                "date": today,
                "name": f"Proposed purchase: {state.purchase_request.item_name}",
                "amount": -purchase,
                "overdue": False,
                "event_type": "purchase",
            }
        ]

        seen_bills = set()

        for bill in state.bill_analysis.bills_detail:
            if not isinstance(bill, dict):
                continue

            mandatory = bill.get("mandatory", True)
            status = str(
                bill.get("status", "pending")
            ).strip().lower()

            if not mandatory:
                continue

            if status in {"paid", "settled", "cancelled", "canceled"}:
                continue

            amount = self._number(
                bill.get("amount", 0),
                "bill.amount",
            )

            if amount <= 0:
                continue

            due_date = self._parse_date(
                bill.get("due_date")
            )

            if due_date is None:
                continue

            if due_date > today + timedelta(days=14):
                continue

            overdue = due_date < today
            display_date = today if overdue else due_date

            bill_id = str(
                bill.get("bill_id", bill.get("name", ""))
            )
            deduplication_key = (
                bill_id,
                due_date.isoformat(),
            )

            if deduplication_key in seen_bills:
                continue

            seen_bills.add(deduplication_key)

            events.append({
                "date": display_date,
                "name": str(
                    bill.get("name", "Mandatory bill")
                ),
                "amount": -amount,
                "overdue": overdue,
                "event_type": "bill",
            })

        events.sort(
            key=lambda event: (
                event["date"],
                0 if event["event_type"] == "purchase" else 1,
            )
        )

        timeline = []

        for event in events:
            current_balance += event["amount"]

            if event["event_type"] == "purchase":
                status = (
                    "PROJECTED_DEFICIT"
                    if current_balance < 0
                    else "PROPOSED"
                )
                description = event["name"]

            elif event["overdue"]:
                status = (
                    "OVERDUE_PROJECTED_DEFICIT"
                    if current_balance < 0
                    else "OVERDUE"
                )
                description = (
                    f"{event['name']} (already overdue; "
                    "payment not confirmed)"
                )

            else:
                status = (
                    "PROJECTED_DEFICIT"
                    if current_balance < 0
                    else "PROJECTED"
                )
                description = event["name"]

            timeline.append(
                TimelineCashEvent(
                    date=event["date"].isoformat(),
                    event=description,
                    cash_in_out=round(event["amount"], 2),
                    projected_balance=round(current_balance, 2),
                    status=status,
                )
            )

        return timeline, current_balance

    def _determine_verdict(
        self,
        state: FinGuardState,
        initial_verdict: str,
        invariant_warnings: List[str],
    ) -> str:
        """
        Apply deterministic safety overrides to the affordability result.
        """
        request_amount = self._number(
            state.purchase_request.amount,
            "purchase_amount",
        )
        checking = self._number(
            state.checking.available_balance,
            "checking_balance",
        )

        post_purchase = checking - request_amount

        overdue = self._number(
            state.bill_analysis.total_overdue_bills,
            "total_overdue_bills",
        )
        upcoming_7d = self._number(
            state.bill_analysis.total_upcoming_bills_7d,
            "total_upcoming_bills_7d",
        )

        projected_after_obligations = (
            post_purchase - overdue - upcoming_7d
        )

        allowed_verdicts = {
            "CAN_AFFORD",
            "CANNOT_AFFORD",
            "CONDITIONAL_AFFORD",
            "CRITICAL_DEFICIT",
        }

        if initial_verdict not in allowed_verdicts:
            raise ValueError(
                f"Unsupported affordability verdict: {initial_verdict}"
            )

        # An immediate negative checking balance is the strongest
        # deterministic warning.
        if post_purchase < 0:
            return "CRITICAL_DEFICIT"

        # A purchase that leaves insufficient funds for known
        # overdue and upcoming mandatory bills cannot be approved.
        if projected_after_obligations < 0:
            return "CANNOT_AFFORD"

        if state.goal_progress.violates_emergency_reserve_floor:
            return "CANNOT_AFFORD"

        if invariant_warnings:
            return "CANNOT_AFFORD"

        # Preserve more cautious decisions from the evaluator.
        if initial_verdict != "CAN_AFFORD":
            return initial_verdict

        if state.budget_analysis.exceeds_budget_if_purchased:
            return "CONDITIONAL_AFFORD"

        if state.cash_flow.will_trigger_overdraft:
            return "CANNOT_AFFORD"

        trajectory = str(
            state.cash_flow.cash_flow_trajectory
        ).upper()

        if trajectory in {
            "TIGHT",
            "NEGATIVE",
            "SEVERE_DEFICIT",
        }:
            return "CONDITIONAL_AFFORD"

        return "CAN_AFFORD"

    def run(self, state: FinGuardState) -> FinGuardState:
        start_time = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "ADK",
            "Synthesizing multi-agent financial findings",
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "ADK",
            "synthesize_final_verdict",
        )

        try:
            req = state.purchase_request
            chk = state.checking
            cc = state.credit_card
            sav = state.savings
            inv = state.investment
            bills = state.bill_analysis
            budget = state.budget_analysis
            cash_flow = state.cash_flow
            goals = state.goal_progress
            risk = state.risk_assessment
            afford = state.affordability

            today = date.today()

            purchase_amount = self._number(
                req.amount,
                "purchase_amount",
            )
            checking_balance = self._number(
                chk.available_balance,
                "checking.available_balance",
            )
            post_purchase_balance = (
                checking_balance - purchase_amount
            )

            # -------------------------------------------------
            # 1. Apply mathematical and liquidity invariants
            # -------------------------------------------------

            initial_verdict = str(afford.verdict)

            verdict_after_invariants, invariant_warnings = (
                FinGuardGuardrails.enforce_mathematical_invariants(
                    verdict=initial_verdict,
                    checking_balance=checking_balance,
                    purchase_amount=purchase_amount,
                    rent_due_days=bills.days_to_next_major_bill,
                    rent_amount=bills.next_major_bill_amount,
                )
            )

            verdict = self._determine_verdict(
                state,
                verdict_after_invariants,
                invariant_warnings,
            )

            # -------------------------------------------------
            # 2. Build warnings
            # -------------------------------------------------

            critical_warnings = list(risk.anomaly_flags)

            for warning in invariant_warnings:
                self._unique_append(
                    critical_warnings,
                    warning,
                )

            overdue_amount = self._number(
                bills.total_overdue_bills,
                "total_overdue_bills",
            )

            if overdue_amount > 0:
                self._unique_append(
                    critical_warnings,
                    (
                        f"Overdue mandatory obligations total "
                        f"${overdue_amount:,.2f}. Their payment "
                        "has not been confirmed."
                    ),
                )

            if budget.exceeds_budget_if_purchased:
                self._unique_append(
                    critical_warnings,
                    (
                        f"Budget overage: '{req.category}' would "
                        f"exceed its available budget by "
                        f"${budget.projected_overage_amount:,.2f}."
                    ),
                )

            if goals.violates_emergency_reserve_floor:
                self._unique_append(
                    critical_warnings,
                    (
                        "Emergency reserve risk: a potential "
                        "checking shortfall could require funds "
                        "below the configured locked reserve."
                    ),
                )

            if cash_flow.will_trigger_overdraft:
                self._unique_append(
                    critical_warnings,
                    "The cash-flow analysis predicts an overdraft risk.",
                )

            # -------------------------------------------------
            # 3. Badge color
            # -------------------------------------------------

            badge_colors = {
                "CAN_AFFORD": "#28a745",
                "CANNOT_AFFORD": "#dc3545",
                "CONDITIONAL_AFFORD": "#fd7e14",
                "CRITICAL_DEFICIT": "#721c24",
            }

            badge_color = badge_colors[verdict]

            # -------------------------------------------------
            # 4. Confidence validation
            # -------------------------------------------------

            confidence = self._number(
                afford.confidence_score,
                "affordability.confidence_score",
            )

            confidence = max(
                0.0,
                min(1.0, confidence),
            )

            # -------------------------------------------------
            # 5. Executive headline and summary
            # -------------------------------------------------

            upcoming_7d = self._number(
                bills.total_upcoming_bills_7d,
                "total_upcoming_bills_7d",
            )

            projected_after_bills = (
                post_purchase_balance
                - overdue_amount
                - upcoming_7d
            )

            if verdict == "CAN_AFFORD":
                headline = (
                    f"You can afford the {req.item_name} "
                    f"(${purchase_amount:,.2f}) based on the "
                    "available financial information."
                )
                summary = (
                    f"Your checking balance is "
                    f"${checking_balance:,.2f}. After the proposed "
                    f"purchase, ${post_purchase_balance:,.2f} "
                    f"would remain. Known overdue and next-7-day "
                    f"mandatory obligations total "
                    f"${overdue_amount + upcoming_7d:,.2f}. "
                    f"The projected balance after these obligations "
                    f"is ${projected_after_bills:,.2f}."
                )

            elif verdict == "CANNOT_AFFORD":
                headline = (
                    f"Do not buy the {req.item_name} "
                    f"(${purchase_amount:,.2f}) right now."
                )
                summary = (
                    "The purchase conflicts with at least one "
                    "important financial safety condition. "
                    f"After the purchase and known overdue and "
                    f"next-7-day mandatory obligations, the "
                    f"projected checking balance is "
                    f"${projected_after_bills:,.2f}. "
                    "Review the warnings and settle essential "
                    "obligations before proceeding."
                )

            elif verdict == "CONDITIONAL_AFFORD":
                headline = (
                    f"Proceed cautiously with the {req.item_name}: "
                    "your financial safety margin is limited."
                )
                summary = (
                    f"The purchase leaves "
                    f"${post_purchase_balance:,.2f} in checking "
                    "before upcoming obligations. "
                    f"Projected cash runway after purchase: "
                    f"{cash_flow.projected_cash_runway_days} days. "
                    "Review budget and cash-flow warnings before "
                    "making a decision."
                )

            else:
                headline = (
                    f"Critical deficit: do not purchase "
                    f"{req.item_name} right now."
                )
                summary = (
                    f"The purchase exceeds your available checking "
                    f"balance by ${abs(post_purchase_balance):,.2f}. "
                    "Proceeding could leave insufficient funds "
                    "for essential payments."
                )

            # -------------------------------------------------
            # 6. Financial metrics table
            # -------------------------------------------------

            budget_remaining = self._number(
                budget.remaining_budget,
                "budget.remaining_budget",
            )
            monthly_limit = self._number(
                budget.monthly_limit,
                "budget.monthly_limit",
            )
            savings_balance = self._number(
                sav.current_balance,
                "savings.current_balance",
            )
            savings_target = self._number(
                sav.target_emergency_reserve,
                "savings.target_emergency_reserve",
            )
            investment_value = self._number(
                inv.total_portfolio_value,
                "investment.total_portfolio_value",
            )
            utilization = self._number(
                cc.utilization_rate_pct,
                "credit_card.utilization_rate_pct",
            )
            apr = self._number(
                cc.apr_percentage,
                "credit_card.apr_percentage",
            )

            post_purchase_budget = (
                budget_remaining - purchase_amount
            )

            metrics_table = [
                FinancialMetricRow(
                    metric="Checking Account Available",
                    current_value=f"${checking_balance:,.2f}",
                    post_purchase_value=(
                        f"${post_purchase_balance:,.2f}"
                    ),
                    status=(
                        "CRITICAL"
                        if post_purchase_balance < 0
                        else "HEALTHY"
                    ),
                    impact=f"-${purchase_amount:,.2f}",
                ),
                FinancialMetricRow(
                    metric="Overdue Mandatory Bills",
                    current_value=f"${overdue_amount:,.2f}",
                    post_purchase_value=f"${overdue_amount:,.2f}",
                    status=(
                        "OVERDUE"
                        if overdue_amount > 0
                        else "CLEAR"
                    ),
                    impact="Outstanding obligations",
                ),
                FinancialMetricRow(
                    metric="Upcoming Mandatory Bills (7 Days)",
                    current_value=f"${upcoming_7d:,.2f}",
                    post_purchase_value=f"${upcoming_7d:,.2f}",
                    status=(
                        "AT_RISK"
                        if projected_after_bills < 0
                        else "PROJECTED"
                    ),
                    impact="Due within 7 days",
                ),
                FinancialMetricRow(
                    metric="Category Budget Remaining",
                    current_value=f"${budget_remaining:,.2f}",
                    post_purchase_value=(
                        f"${post_purchase_budget:,.2f}"
                    ),
                    status=(
                        "DEFICIT"
                        if budget.exceeds_budget_if_purchased
                        else "OK"
                    ),
                    impact=f"Limit: ${monthly_limit:,.2f}",
                ),
                FinancialMetricRow(
                    metric="Credit Card Utilization",
                    current_value=f"{utilization:.1f}%",
                    post_purchase_value=(
                        f"{utilization:.1f}% (unchanged)"
                    ),
                    status=(
                        "HIGH"
                        if utilization > 50
                        else "NORMAL"
                    ),
                    impact=f"APR: {apr:.2f}%",
                ),
                FinancialMetricRow(
                    metric="Emergency Reserve",
                    current_value=f"${savings_balance:,.2f}",
                    post_purchase_value=(
                        f"${savings_balance:,.2f} (not withdrawn)"
                    ),
                    status=(
                        "FLOOR_RISK"
                        if goals.violates_emergency_reserve_floor
                        else "PROTECTED"
                    ),
                    impact=(
                        f"Target: ${savings_target:,.2f}; "
                        f"coverage: "
                        f"{goals.emergency_fund_coverage_pct:.1f}%"
                    ),
                ),
                FinancialMetricRow(
                    metric="Investment Portfolio",
                    current_value=f"${investment_value:,.2f}",
                    post_purchase_value=(
                        f"${investment_value:,.2f} (unchanged)"
                    ),
                    status=(
                        "VOLATILE"
                        if inv.volatility_alert
                        else "STABLE"
                    ),
                    impact="Long-term investment value",
                ),
            ]

            # -------------------------------------------------
            # 7. Dynamic 14-day cash-flow timeline
            # -------------------------------------------------

            cash_timeline, _ = self._build_cash_timeline(
                state,
                today,
            )

            if not any(
                "already overdue" in event.event.lower()
                for event in cash_timeline
            ) and overdue_amount > 0:
                self._unique_append(
                    critical_warnings,
                    (
                        "Overdue bill details were not available "
                        "for the projected timeline."
                    ),
                )

            # -------------------------------------------------
            # 8. Actionable alternatives
            # -------------------------------------------------

            actionable_steps = []

            if verdict in {
                "CANNOT_AFFORD",
                "CRITICAL_DEFICIT",
            }:
                actionable_steps.append(
                    "Postpone the purchase until checking funds "
                    "are sufficient and essential obligations "
                    "are covered."
                )

                safe_purchase_limit = max(
                    0.0,
                    checking_balance
                    - overdue_amount
                    - upcoming_7d,
                )

                actionable_steps.append(
                    "Consider a lower-cost alternative that keeps "
                    f"the purchase below ${safe_purchase_limit:,.2f}, "
                    "subject to your emergency reserve and budget."
                )

                if cc.current_balance > 0:
                    actionable_steps.append(
                        "Review your existing credit-card balance "
                        "and upcoming minimum payment before "
                        "taking on additional discretionary spending."
                    )

            elif verdict == "CONDITIONAL_AFFORD":
                actionable_steps.append(
                    "Review your remaining category budget and "
                    "cash-flow runway before purchasing."
                )
                actionable_steps.append(
                    "Protect the emergency reserve and ensure "
                    "mandatory bills are covered."
                )
                actionable_steps.append(
                    "Consider postponing the purchase or choosing "
                    "a less expensive alternative."
                )

            else:
                actionable_steps.append(
                    "Keep the purchase within the available "
                    "category budget."
                )
                actionable_steps.append(
                    "Track the transaction in your spending ledger "
                    "and continue monitoring upcoming obligations."
                )

            # -------------------------------------------------
            # 9. Structured final verdict
            # -------------------------------------------------

            final_verdict = FinGuardVerdict(
                item_name=req.item_name,
                amount=purchase_amount,
                category=req.category,
                verdict=verdict,
                verdict_badge_color=badge_color,
                confidence_score=confidence,
                headline=headline,
                executive_summary=summary,
                metrics_table=metrics_table,
                cash_flow_timeline=cash_timeline,
                critical_warnings=critical_warnings,
                actionable_alternatives=actionable_steps,
                risk_breakdown=risk.model_dump(),
                provenance_trace_id=state.trace_id,
            )

            state.final_verdict = final_verdict

            duration_ms = (
                time.time() - start_time
            ) * 1000.0

            self.callbacks.on_state_update(
                self.name,
                "ADK",
                "state.final_verdict",
                f"{verdict}: {headline}",
            )

            self.callbacks.on_agent_finish(
                self.name,
                "ADK",
                f"Verdict formulated: {verdict}",
                duration_ms,
            )

            self.observability.end_span(
                state.trace_id,
                span,
                {
                    "final_verdict": final_verdict.model_dump(),
                },
                duration_ms,
            )

            state.add_trace(
                self.name,
                "ADK",
                "Final Verdict Synthesis",
                "SUCCESS",
                "Synthesize financial agent evaluations",
                f"Verdict: {verdict}",
                duration_ms,
            )

            return state

        except Exception as exc:
            duration_ms = (
                time.time() - start_time
            ) * 1000.0

            logger.exception(
                "Coordinator Agent failed: %s",
                exc,
            )

            self.callbacks.on_agent_finish(
                self.name,
                "ADK",
                f"FAILED: {exc}",
                duration_ms,
            )

            self.observability.end_span(
                state.trace_id,
                span,
                {"error": str(exc)},
                duration_ms,
            )

            state.add_trace(
                self.name,
                "ADK",
                "Final Verdict Synthesis",
                "FAILED",
                "Synthesize financial agent evaluations",
                str(exc),
                duration_ms,
            )

            raise

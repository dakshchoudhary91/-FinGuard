
"""
Agent 5: Risk / Anomaly Agent (Google ADK Framework).

Evaluates liquidity, credit utilization, upcoming bill pressure,
and market volatility. Produces a composite risk score from 0–100.
"""

import math
import time
from typing import List

from agents.adk_framework.base import ADKDomainService
from core.state import FinGuardState, RiskAssessmentState


class RiskAnomalyAgent(ADKDomainService):

    def __init__(self):
        super().__init__(
            agent_id="adk_risk_anomaly",
            name="Risk / Anomaly Agent",
            role="Systemic Financial Risk & Anomaly Detector",
            instructions=(
                "Analyze financial risk using account liquidity, credit "
                "utilization, upcoming bill obligations, and market signals. "
                "Produce an evidence-based risk score from 0 to 100."
            )
        )

    @staticmethod
    def _number(value, field_name: str) -> float:
        """Convert a value to a finite float or reject invalid input."""
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid numeric value for {field_name}: {value}")

        if not math.isfinite(result):
            raise ValueError(f"Non-finite value for {field_name}")

        return result

    @staticmethod
    def _risk_level(score: int) -> str:
        if score >= 70:
            return "CRITICAL"
        if score >= 50:
            return "ELEVATED"
        if score >= 30:
            return "MODERATE"
        return "SAFE"

    def run(self, state: FinGuardState) -> FinGuardState:
        started_at = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "ADK",
            "Evaluating systemic financial risks"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "ADK",
            "assess_financial_risk"
        )

        try:
            flags: List[str] = []
            risk_score = 0

            # --------------------------------------------------
            # 1. Checking account liquidity
            # --------------------------------------------------

            available_checking = self._number(
                state.checking.available_balance,
                "checking.available_balance"
            )

            purchase_amount = self._number(
                state.purchase_request.amount,
                "purchase_request.amount"
            )

            if available_checking < 0 or purchase_amount < 0:
                raise ValueError(
                    "Checking balance and purchase amount cannot be negative."
                )

            post_purchase_balance = (
                available_checking - purchase_amount
            )

            if post_purchase_balance < 0:
                deficit = abs(post_purchase_balance)

                flags.append(
                    f"LIQUIDITY DEFICIT: The purchase exceeds available "
                    f"checking funds by ${deficit:,.2f}."
                )
                risk_score += 45

            elif post_purchase_balance < 100:
                flags.append(
                    f"LOW CASH BUFFER: Only "
                    f"${post_purchase_balance:,.2f} remains after purchase."
                )
                risk_score += 20

            # --------------------------------------------------
            # 2. Credit card utilization
            # --------------------------------------------------

            utilization = self._number(
                state.credit_card.utilization_rate_pct,
                "credit_card.utilization_rate_pct"
            )

            if utilization < 0:
                raise ValueError(
                    "Credit utilization cannot be negative."
                )

            if utilization > 60:
                flags.append(
                    f"HIGH CREDIT UTILIZATION: Card utilization is "
                    f"{utilization:.1f}%, above the 60% risk threshold."
                )
                risk_score += 20

            elif utilization > 30:
                flags.append(
                    f"ELEVATED CREDIT UTILIZATION: Card utilization is "
                    f"{utilization:.1f}%, above the 30% monitoring threshold."
                )
                risk_score += 10

            # --------------------------------------------------
            # 3. Upcoming bill collision
            # --------------------------------------------------

            upcoming_bills = self._number(
                state.bill_analysis.total_upcoming_bills_7d,
                "bill_analysis.total_upcoming_bills_7d"
            )

            if upcoming_bills < 0:
                raise ValueError(
                    "Upcoming bill total cannot be negative."
                )

            days_to_next_bill = self._number(
                state.bill_analysis.days_to_next_major_bill,
                "bill_analysis.days_to_next_major_bill"
            )

            bill_collision = (
                state.bill_analysis.immediate_shortfall_risk
                or (
                    days_to_next_bill <= 5
                    and post_purchase_balance < upcoming_bills
                )
            )

            if bill_collision:
                bill_name = (
                    state.bill_analysis.next_major_bill_name
                    or "Upcoming mandatory bill"
                )

                bill_amount = self._number(
                    state.bill_analysis.next_major_bill_amount,
                    "bill_analysis.next_major_bill_amount"
                )

                if days_to_next_bill < 0:
                    due_description = (
                        f"{abs(days_to_next_bill):.0f} days overdue"
                    )
                elif days_to_next_bill == 0:
                    due_description = "due today"
                else:
                    due_description = (
                        f"due in {days_to_next_bill:.0f} days"
                    )

                flags.append(
                    f"BILL COLLISION: {bill_name} "
                    f"(${bill_amount:,.2f}) is {due_description}. "
                    f"Post-purchase checking balance "
                    f"(${post_purchase_balance:,.2f}) is insufficient "
                    f"for the upcoming 7-day bill obligations "
                    f"(${upcoming_bills:,.2f})."
                )

                risk_score += 25

            # --------------------------------------------------
            # 4. Investment market volatility
            # --------------------------------------------------

            volatility_alert = (
                state.investment.volatility_alert
            )

            market_risk_detected = bool(volatility_alert)

            if market_risk_detected:
                flags.append(
                    f"MARKET VOLATILITY: {volatility_alert}"
                )
                risk_score += 5

            # --------------------------------------------------
            # 5. Final risk calculation
            # --------------------------------------------------

            risk_score = min(100, max(0, int(risk_score)))
            risk_level = self._risk_level(risk_score)

            liquidity_crisis = (
                post_purchase_balance < 0
                or post_purchase_balance < upcoming_bills
            )

            credit_danger = utilization > 50

            summary = (
                f"Risk Level: {risk_level} "
                f"(Score: {risk_score}/100). "
                f"Detected factors: "
                f"{'; '.join(flags) if flags else 'No adverse risk indicators identified.'}"
            )

            state.risk_assessment = RiskAssessmentState(
                risk_score=risk_score,
                risk_level=risk_level,
                anomaly_flags=flags,
                credit_utilization_danger=credit_danger,
                liquidity_crisis_danger=liquidity_crisis,
                market_drawdown_exposure=market_risk_detected,
                risk_summary=summary
            )

            # --------------------------------------------------
            # 6. A2A message to Coordinator
            # --------------------------------------------------

            self.send_a2a_message(
                recipient_id="adk_coordinator",
                recipient_framework="ADK",
                recipient_role="Coordinator Synthesizer",
                topic="risk_assessment_result",
                content={
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "anomaly_flags": flags,
                    "credit_utilization_danger": credit_danger,
                    "liquidity_crisis_danger": liquidity_crisis,
                    "market_drawdown_exposure": market_risk_detected,
                    "post_purchase_checking": post_purchase_balance,
                    "upcoming_bills_7d": upcoming_bills
                },
                trace_id=state.trace_id
            )

            # --------------------------------------------------
            # 7. Monitoring and trace
            # --------------------------------------------------

            duration_ms = (time.time() - started_at) * 1000

            self.callbacks.on_state_update(
                self.name,
                "ADK",
                "state.risk_assessment",
                f"{risk_level} ({risk_score}/100)"
            )

            self.callbacks.on_agent_finish(
                self.name,
                "ADK",
                summary,
                duration_ms
            )

            self.observability.end_span(
                state.trace_id,
                span,
                {
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "anomaly_flags": flags
                },
                duration_ms
            )

            state.add_trace(
                self.name,
                "ADK",
                "Systemic Risk Evaluation",
                "SUCCESS",
                "Evaluate liquidity, credit, bills and market risks",
                summary,
                duration_ms
            )

            return state

        except Exception as exc:
            duration_ms = (time.time() - started_at) * 1000

            self.callbacks.on_agent_finish(
                self.name,
                "ADK",
                f"Risk assessment failed: {exc}",
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
                "ADK",
                "Systemic Risk Evaluation",
                "FAILED",
                "Evaluate financial risks",
                str(exc),
                duration_ms
            )

            raise

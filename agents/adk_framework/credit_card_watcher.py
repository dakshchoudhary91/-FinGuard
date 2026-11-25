
"""
Agent 2: Credit Card Watcher (Google ADK Framework).

Retrieves credit-card account information through MCP, validates
financial values, calculates utilization, and reports risk signals.
"""

import math
import time
from datetime import date

from agents.adk_framework.base import ADKDomainService
from core.state import FinGuardState, CreditCardState


class CreditCardWatcherAgent(ADKDomainService):

    def __init__(self):
        super().__init__(
            agent_id="adk_credit_card_watcher",
            name="Credit Card Watcher",
            role="Credit Utilization & Debt Monitor",
            instructions=(
                "Monitor credit card balances, credit limits, APR, "
                "minimum payments, payment dates, and utilization. "
                "Validate account information before updating shared state."
            )
        )

    @staticmethod
    def _number(value, field_name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid numeric value for {field_name}: {value}"
            )

        if not math.isfinite(result):
            raise ValueError(
                f"Non-finite value for {field_name}"
            )

        return result

    @staticmethod
    def _validate_due_date(value) -> str:
        """
        Validate an ISO-format payment date.
        An unavailable date is represented by an empty string.
        """
        if value in (None, ""):
            return ""

        date_value = str(value).strip()

        try:
            date.fromisoformat(date_value)
        except ValueError:
            raise ValueError(
                f"Invalid credit-card payment due date: {date_value}"
            )

        return date_value

    def run(self, state: FinGuardState) -> FinGuardState:
        started_at = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "ADK",
            "Querying credit-card account through Plaid MCP"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "ADK",
            "query_credit_card"
        )

        try:
            # ----------------------------------------------
            # 1. Retrieve credit-card account information
            # ----------------------------------------------

            tool_resp = self.call_mcp_tool(
                "plaid_db_lookup",
                {
                    "account_type": "credit_card",
                    "include_transactions": True
                }
            )

            if not isinstance(tool_resp, dict):
                raise ValueError(
                    "MCP returned an invalid credit-card response."
                )

            acc_data = tool_resp.get("account")

            if not isinstance(acc_data, dict) or not acc_data:
                raise ValueError(
                    "MCP response does not contain a valid credit-card account."
                )

            # ----------------------------------------------
            # 2. Validate required financial information
            # ----------------------------------------------

            if "current_balance" not in acc_data:
                raise ValueError(
                    "Credit-card current_balance is missing from MCP data."
                )

            if "credit_limit" not in acc_data:
                raise ValueError(
                    "Credit-card credit_limit is missing from MCP data."
                )

            current_balance = self._number(
                acc_data["current_balance"],
                "current_balance"
            )

            credit_limit = self._number(
                acc_data["credit_limit"],
                "credit_limit"
            )

            if current_balance < 0:
                raise ValueError(
                    "Credit-card balance cannot be negative."
                )

            if credit_limit <= 0:
                raise ValueError(
                    "Credit limit must be greater than zero."
                )

            # ----------------------------------------------
            # 3. Calculate available credit and utilization
            # ----------------------------------------------

            available_credit = credit_limit - current_balance

            utilization = (
                current_balance / credit_limit
            ) * 100.0

            utilization = round(utilization, 2)

            # ----------------------------------------------
            # 4. Validate optional account information
            # ----------------------------------------------

            apr = self._number(
                acc_data.get(
                    "apr_percentage",
                    CreditCardState.model_fields[
                        "apr_percentage"
                    ].default
                ),
                "apr_percentage"
            )

            minimum_payment = self._number(
                acc_data.get(
                    "minimum_payment",
                    CreditCardState.model_fields[
                        "minimum_payment"
                    ].default
                ),
                "minimum_payment"
            )

            if apr < 0:
                raise ValueError(
                    "APR cannot be negative."
                )

            if minimum_payment < 0:
                raise ValueError(
                    "Minimum payment cannot be negative."
                )

            due_date = self._validate_due_date(
                acc_data.get("next_payment_due_date")
            )

            # ----------------------------------------------
            # 5. Update shared financial state
            # ----------------------------------------------

            state.credit_card = CreditCardState(
                account_id=str(
                    acc_data.get("account_id", "acc_cc_02")
                ),
                name=str(
                    acc_data.get(
                        "name",
                        "Cash Rewards Platinum Card"
                    )
                ),
                current_balance=current_balance,
                credit_limit=credit_limit,
                available_credit=round(available_credit, 2),
                apr_percentage=apr,
                minimum_payment=minimum_payment,
                next_payment_due_date=due_date,
                utilization_rate_pct=utilization
            )

            # ----------------------------------------------
            # 6. Determine credit risk indicators
            # ----------------------------------------------

            if utilization > 60:
                utilization_status = "HIGH"
            elif utilization > 30:
                utilization_status = "ELEVATED"
            else:
                utilization_status = "NORMAL"

            credit_danger = utilization > 50

            # ----------------------------------------------
            # 7. A2A notification to Risk Agent
            # ----------------------------------------------

            self.send_a2a_message(
                recipient_id="adk_risk_anomaly",
                recipient_framework="ADK",
                recipient_role="Risk & Anomaly Evaluator",
                topic="credit_utilization_alert",
                content={
                    "utilization_pct": utilization,
                    "current_balance": current_balance,
                    "credit_limit": credit_limit,
                    "available_credit": round(
                        available_credit, 2
                    ),
                    "apr_percentage": apr,
                    "minimum_payment": minimum_payment,
                    "next_payment_due_date": due_date,
                    "utilization_status": utilization_status,
                    "is_danger": credit_danger
                },
                trace_id=state.trace_id
            )

            # ----------------------------------------------
            # 8. Monitoring and observability
            # ----------------------------------------------

            duration_ms = (
                time.time() - started_at
            ) * 1000.0

            summary = (
                f"Credit Balance: ${current_balance:,.2f} / "
                f"${credit_limit:,.2f} "
                f"({utilization:.2f}% utilization). "
                f"Available credit: ${available_credit:,.2f}. "
                f"Utilization status: {utilization_status}."
            )

            self.callbacks.on_state_update(
                self.name,
                "ADK",
                "state.credit_card",
                summary
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
                    "credit_card": (
                        state.credit_card.model_dump()
                    ),
                    "utilization_status": utilization_status
                },
                duration_ms,
                mcp_tools=["plaid_db_lookup"]
            )

            state.add_trace(
                self.name,
                "ADK",
                "Credit Card Lookup",
                "SUCCESS",
                "Validate credit-card balance and utilization",
                summary,
                duration_ms
            )

            return state

        except Exception as exc:
            duration_ms = (
                time.time() - started_at
            ) * 1000.0

            self.callbacks.on_agent_finish(
                self.name,
                "ADK",
                f"Credit-card lookup failed: {exc}",
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
                "Credit Card Lookup",
                "FAILED",
                "Retrieve and validate credit-card information",
                str(exc),
                duration_ms
            )

            raise

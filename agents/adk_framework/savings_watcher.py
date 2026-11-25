
"""
Agent 3: Savings Account Watcher (Google ADK Framework).

Retrieves savings account information through MCP, validates financial
values, calculates the available buffer above the emergency target,
and reports reserve impact to the Goal Progress Agent.
"""

import math
import time

from agents.adk_framework.base import ADKDomainService
from core.state import FinGuardState, SavingsAccountState


class SavingsWatcherAgent(ADKDomainService):

    def __init__(self):
        super().__init__(
            agent_id="adk_savings_watcher",
            name="Savings Account Watcher",
            role="Emergency Reserve & Yield Monitor",
            instructions=(
                "Monitor savings balances, available funds, APY, and "
                "emergency reserve coverage. Validate account data and "
                "assess the effect of a proposed purchase on savings."
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

    def run(self, state: FinGuardState) -> FinGuardState:
        started_at = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "ADK",
            "Querying savings account through Plaid MCP"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "ADK",
            "query_savings_balance"
        )

        try:
            # ----------------------------------------------
            # 1. Retrieve savings account information
            # ----------------------------------------------

            tool_resp = self.call_mcp_tool(
                "plaid_db_lookup",
                {
                    "account_type": "savings",
                    "include_transactions": False
                }
            )

            if not isinstance(tool_resp, dict):
                raise ValueError(
                    "MCP returned an invalid savings response."
                )

            acc_data = tool_resp.get("account")

            if not isinstance(acc_data, dict) or not acc_data:
                raise ValueError(
                    "MCP response does not contain a valid savings account."
                )

            if "current_balance" not in acc_data:
                raise ValueError(
                    "Savings current_balance is missing from MCP data."
                )

            if "target_emergency_reserve" not in acc_data:
                raise ValueError(
                    "Emergency reserve target is missing from MCP data."
                )

            current_balance = self._number(
                acc_data["current_balance"],
                "current_balance"
            )

            target_emergency = self._number(
                acc_data["target_emergency_reserve"],
                "target_emergency_reserve"
            )

            if current_balance < 0:
                raise ValueError(
                    "Savings balance cannot be negative."
                )

            if target_emergency <= 0:
                raise ValueError(
                    "Emergency reserve target must be greater than zero."
                )

            # ----------------------------------------------
            # 2. Validate available savings balance
            # ----------------------------------------------

            available_balance = self._number(
                acc_data.get("available_balance", current_balance),
                "available_balance"
            )

            if available_balance < 0:
                raise ValueError(
                    "Available savings balance cannot be negative."
                )

            if available_balance > current_balance:
                raise ValueError(
                    "Available savings balance cannot exceed current balance."
                )

            # ----------------------------------------------
            # 3. Validate APY
            # ----------------------------------------------

            interest_rate = self._number(
                acc_data.get(
                    "interest_rate_apy",
                    SavingsAccountState.model_fields[
                        "interest_rate_apy"
                    ].default
                ),
                "interest_rate_apy"
            )

            if interest_rate < 0:
                raise ValueError(
                    "Savings APY cannot be negative."
                )

            # ----------------------------------------------
            # 4. Validate proposed purchase amount
            # ----------------------------------------------

            purchase_amount = self._number(
                state.purchase_request.amount,
                "purchase_request.amount"
            )

            if purchase_amount < 0:
                raise ValueError(
                    "Purchase amount cannot be negative."
                )

            # ----------------------------------------------
            # 5. Calculate emergency reserve impact via MCP
            # ----------------------------------------------

            buffer_calc = self.call_mcp_tool(
                "financial_calculator",
                {
                    "calc_type": "buffer_impact",
                    "liquid_cash": available_balance,
                    "purchase_amount": purchase_amount,
                    "emergency_target": target_emergency
                }
            )

            if not isinstance(buffer_calc, dict):
                raise ValueError(
                    "Financial calculator returned an invalid buffer response."
                )

            required_fields = [
                "post_purchase_liquid",
                "reserve_deficit",
                "cushion_coverage_pct",
                "floor_breached"
            ]

            missing_fields = [
                field for field in required_fields
                if field not in buffer_calc
            ]

            if missing_fields:
                raise ValueError(
                    "Buffer calculation is missing fields: "
                    + ", ".join(missing_fields)
                )

            post_purchase_liquid = self._number(
                buffer_calc["post_purchase_liquid"],
                "buffer_calc.post_purchase_liquid"
            )

            reserve_deficit = self._number(
                buffer_calc["reserve_deficit"],
                "buffer_calc.reserve_deficit"
            )

            cushion_coverage = self._number(
                buffer_calc["cushion_coverage_pct"],
                "buffer_calc.cushion_coverage_pct"
            )

            if reserve_deficit < 0:
                raise ValueError(
                    "Reserve deficit cannot be negative."
                )

            if not isinstance(buffer_calc["floor_breached"], bool):
                raise ValueError(
                    "Buffer calculation floor_breached must be boolean."
                )

            # ----------------------------------------------
            # 6. Calculate available buffer above target
            # ----------------------------------------------

            safe_buffer = max(
                0.0,
                available_balance - target_emergency
            )

            post_purchase_buffer = max(
                0.0,
                post_purchase_liquid - target_emergency
            )

            reserve_breached = buffer_calc["floor_breached"]

            # ----------------------------------------------
            # 7. Update shared savings state
            # ----------------------------------------------

            state.savings = SavingsAccountState(
                account_id=str(
                    acc_data.get("account_id", "acc_sav_03")
                ),
                name=str(
                    acc_data.get(
                        "name",
                        "High Yield Emergency Savings"
                    )
                ),
                current_balance=current_balance,
                available_balance=available_balance,
                interest_rate_apy=interest_rate,
                target_emergency_reserve=target_emergency,
                safe_buffer_available=round(safe_buffer, 2)
            )

            # ----------------------------------------------
            # 8. A2A notification to Goal Progress Agent
            # ----------------------------------------------

            self.send_a2a_message(
                recipient_id="crewai_goal_progress",
                recipient_framework="CrewAI",
                recipient_role="Goal Progress Analyst",
                topic="emergency_reserve_status",
                content={
                    "savings_balance": current_balance,
                    "available_balance": available_balance,
                    "target_reserve": target_emergency,
                    "safe_buffer": round(safe_buffer, 2),
                    "post_purchase_liquid": round(
                        post_purchase_liquid, 2
                    ),
                    "post_purchase_buffer": round(
                        post_purchase_buffer, 2
                    ),
                    "reserve_deficit": round(
                        reserve_deficit, 2
                    ),
                    "cushion_coverage_pct": round(
                        cushion_coverage, 2
                    ),
                    "floor_breached": reserve_breached,
                    "buffer_calculation": buffer_calc
                },
                trace_id=state.trace_id
            )

            # ----------------------------------------------
            # 9. Monitoring and observability
            # ----------------------------------------------

            duration_ms = (
                time.time() - started_at
            ) * 1000.0

            summary = (
                f"Savings Balance: ${current_balance:,.2f}; "
                f"Available: ${available_balance:,.2f}; "
                f"Emergency Target: ${target_emergency:,.2f}; "
                f"Buffer Above Target: ${safe_buffer:,.2f}; "
                f"Post-Purchase Reserve Breached: "
                f"{reserve_breached}."
            )

            self.callbacks.on_state_update(
                self.name,
                "ADK",
                "state.savings",
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
                    "savings": state.savings.model_dump(),
                    "buffer_calculation": buffer_calc
                },
                duration_ms,
                mcp_tools=[
                    "plaid_db_lookup",
                    "financial_calculator"
                ]
            )

            state.add_trace(
                self.name,
                "ADK",
                "Savings Lookup & Cushion Check",
                "SUCCESS",
                "Validate savings and assess emergency reserve impact",
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
                f"Savings assessment failed: {exc}",
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
                "Savings Lookup & Cushion Check",
                "FAILED",
                "Retrieve and validate savings account information",
                str(exc),
                duration_ms
            )

            raise

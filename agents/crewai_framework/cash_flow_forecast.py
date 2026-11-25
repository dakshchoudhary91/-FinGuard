
"""
Agent 9: Cash-Flow Forecast Agent (CrewAI Framework).

Projects cash after a purchase, overdue obligations, and upcoming bills.
Uses the MCP financial calculator for a bill-based liquidity runway estimate.
"""

import logging
import math
import time

from agents.crewai_framework.crew_bridge import CrewAIDomainService
from core.state import FinGuardState, CashFlowForecastState


logger = logging.getLogger("FinGuard_CashFlow")


class CashFlowForecastAgent(CrewAIDomainService):
    def __init__(self):
        super().__init__(
            agent_id="crewai_cash_flow",
            name="Cash-Flow Forecast Agent",
            role="Dynamic Cash Flow Forecaster & Runway Predictor",
            goal=(
                "Forecast available cash after purchases and outstanding bills, "
                "and identify potential liquidity shortfalls."
            ),
            backstory=(
                "A quantitative treasury specialist who evaluates liquidity, "
                "upcoming obligations, and cash-flow risks using verified financial data."
            )
        )

    def run(self, state: FinGuardState) -> FinGuardState:
        t0 = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "CrewAI",
            "Forecasting cash flow after purchase and outstanding bills"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "CrewAI",
            "forecast_cash_flow"
        )

        try:
            # --------------------------------------------------
            # 1. Read financial inputs
            # --------------------------------------------------
            checking_available = float(
                state.checking.available_balance or 0.0
            )

            purchase_amount = float(
                state.purchase_request.amount or 0.0
            )

            overdue_bills = float(
                state.bill_analysis.total_overdue_bills or 0.0
            )

            upcoming_bills_7d = float(
                state.bill_analysis.total_upcoming_bills_7d or 0.0
            )

            upcoming_bills_30d = float(
                state.bill_analysis.total_upcoming_bills_30d or 0.0
            )

            values = [
                checking_available,
                purchase_amount,
                overdue_bills,
                upcoming_bills_7d,
                upcoming_bills_30d,
            ]

            if not all(math.isfinite(value) for value in values):
                raise ValueError(
                    "Cash-flow inputs contain invalid or non-finite values."
                )

            if any(value < 0 for value in values):
                raise ValueError(
                    "Cash-flow inputs cannot contain negative amounts."
                )

            # --------------------------------------------------
            # 2. Calculate projected balances
            # --------------------------------------------------
            balance_after_purchase = (
                checking_available - purchase_amount
            )

            balance_after_overdue = (
                balance_after_purchase - overdue_bills
            )

            balance_after_7d_obligations = (
                balance_after_overdue - upcoming_bills_7d
            )

            will_overdraft = (
                balance_after_purchase < 0
                or balance_after_overdue < 0
                or balance_after_7d_obligations < 0
            )

            net_7d_cash_flow = -(
                purchase_amount + overdue_bills + upcoming_bills_7d
            )

            # --------------------------------------------------
            # 3. Determine cash-flow trajectory
            # --------------------------------------------------
            next_bill_amount = float(
                state.bill_analysis.next_major_bill_amount or 0.0
            )

            if balance_after_7d_obligations < 0:
                trajectory = "SEVERE_DEFICIT"

            elif (
                next_bill_amount > 0
                and balance_after_7d_obligations < next_bill_amount
            ):
                trajectory = "TIGHT"

            else:
                trajectory = "STABLE"

            # --------------------------------------------------
            # 4. Calculate bill-based runway using MCP
            # --------------------------------------------------
            runway_days = 0
            runway_available = False
            runway_description = "Unavailable"

            # Do not invent food, transport, or other expenses.
            # This is an estimate based only on recorded upcoming bills.
            if upcoming_bills_30d > 0:
                try:
                    runway_result = self.call_mcp_tool(
                        "financial_calculator",
                        {
                            "calc_type": "runway_days",
                            "liquid_cash": max(
                                0.0,
                                checking_available - overdue_bills
                            ),
                            "purchase_amount": purchase_amount,
                            "monthly_expenses": upcoming_bills_30d,
                        }
                    )

                    if not isinstance(runway_result, dict):
                        raise ValueError(
                            "MCP runway result is not a dictionary."
                        )

                    raw_runway = runway_result.get(
                        "post_purchase_runway_days"
                    )

                    if (
                        isinstance(raw_runway, bool)
                        or not isinstance(raw_runway, (int, float))
                        or not math.isfinite(float(raw_runway))
                    ):
                        raise ValueError(
                            "MCP returned an invalid runway value."
                        )

                    runway_days = max(0, int(round(raw_runway)))
                    runway_available = True
                    runway_description = "Bill-based estimate"

                except Exception:
                    logger.exception(
                        "MCP runway calculation failed. "
                        "Runway will be marked unavailable."
                    )

            else:
                logger.info(
                    "Runway not calculated: no upcoming 30-day bills "
                    "are available as an expense estimate."
                )

            # --------------------------------------------------
            # 5. Update shared state
            # --------------------------------------------------
            state.cash_flow = CashFlowForecastState(
                current_liquid_checking=round(
                    checking_available, 2
                ),
                projected_balance_after_purchase=round(
                    balance_after_purchase, 2
                ),
                projected_balance_after_bills_and_purchase=round(
                    balance_after_7d_obligations, 2
                ),
                projected_cash_runway_days=runway_days,
                will_trigger_overdraft=will_overdraft,
                net_7d_cash_flow=round(
                    net_7d_cash_flow, 2
                ),
                cash_flow_trajectory=trajectory
            )

            # --------------------------------------------------
            # 6. Send A2A update to Affordability Evaluator
            # --------------------------------------------------
            self.send_a2a_message(
                recipient_id="crewai_affordability",
                recipient_framework="CrewAI",
                recipient_role="Affordability Evaluator",
                topic="cash_flow_trajectory",
                content={
                    "current_checking_balance": round(
                        checking_available, 2
                    ),
                    "purchase_amount": round(
                        purchase_amount, 2
                    ),
                    "post_purchase_balance": round(
                        balance_after_purchase, 2
                    ),
                    "overdue_bills": round(
                        overdue_bills, 2
                    ),
                    "upcoming_bills_7d": round(
                        upcoming_bills_7d, 2
                    ),
                    "post_bills_balance": round(
                        balance_after_7d_obligations, 2
                    ),
                    "will_overdraft": will_overdraft,
                    "runway_days": runway_days,
                    "runway_available": runway_available,
                    "runway_type": runway_description,
                    "trajectory": trajectory
                },
                trace_id=state.trace_id,
                state_delta={
                    "will_overdraft": will_overdraft
                }
            )

            # --------------------------------------------------
            # 7. Record execution
            # --------------------------------------------------
            duration_ms = (time.time() - t0) * 1000.0

            summary = (
                f"Post-purchase balance: ${balance_after_purchase:,.2f} | "
                f"Overdue bills: ${overdue_bills:,.2f} | "
                f"7-day obligations: ${upcoming_bills_7d:,.2f} | "
                f"Projected balance: ${balance_after_7d_obligations:,.2f} | "
                f"Runway: "
                f"{str(runway_days) + ' days' if runway_available else 'Unavailable'} | "
                f"Trajectory: {trajectory}"
            )

            self.callbacks.on_state_update(
                self.name,
                "CrewAI",
                "state.cash_flow",
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
                    "cash_flow": state.cash_flow.model_dump(),
                    "runway_available": runway_available
                },
                duration_ms,
                mcp_tools=(
                    ["financial_calculator"]
                    if runway_available
                    else []
                )
            )

            state.add_trace(
                self.name,
                "CrewAI",
                "Cash Flow & Runway Simulation",
                "SUCCESS",
                "Forecasted liquidity using purchase and recorded bill obligations",
                summary,
                duration_ms
            )

            return state

        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000.0

            logger.exception(
                "Cash-flow forecasting failed."
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
                "Cash Flow & Runway Simulation",
                "ERROR",
                "Cash-flow forecasting failed",
                str(exc),
                duration_ms
            )

            raise

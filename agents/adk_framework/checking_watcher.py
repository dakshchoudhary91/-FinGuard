
"""
Agent 1: Checking Account Watcher Agent (Google ADK Framework).

Retrieves checking account balances and recent transactions through MCP.
Validates financial data and shares checking liquidity information
with the Cash Flow Forecaster through A2A messaging.
"""

import math
import time

from agents.adk_framework.base import ADKDomainService
from core.state import FinGuardState, CheckingAccountState


class CheckingWatcherAgent(ADKDomainService):

    def __init__(self):
        super().__init__(
            agent_id="adk_checking_watcher",
            name="Checking Account Watcher",
            role="Liquid Cash & Deposit Monitor",
            instructions=(
                "Monitor checking account balances, available liquidity, "
                "overdraft protection, and recent transactions. "
                "Validate account data before sharing it with other agents."
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
                f"Non-finite value for {field_name}."
            )

        return result

    @classmethod
    def _validate_transactions(cls, transactions):
        if not isinstance(transactions, list):
            raise ValueError(
                "Recent transactions must be a list."
            )

        validated = []

        for index, transaction in enumerate(transactions):
            if not isinstance(transaction, dict):
                raise ValueError(
                    f"Invalid transaction at index {index}."
                )

            if "amount" in transaction:
                amount = cls._number(
                    transaction["amount"],
                    f"transactions[{index}].amount"
                )

                if amount < 0:
                    raise ValueError(
                        f"Negative transaction amount at index {index}."
                    )

            validated.append(dict(transaction))

        return validated

    def run(self, state: FinGuardState) -> FinGuardState:

        started_at = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "ADK",
            (
                "Inspecting checking account for purchase: "
                f"${state.purchase_request.amount:.2f}"
            )
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "ADK",
            "query_checking_balance"
        )

        try:
            # ------------------------------------------
            # 1. Retrieve checking account through MCP
            # ------------------------------------------

            tool_resp = self.call_mcp_tool(
                "plaid_db_lookup",
                {
                    "account_type": "checking",
                    "include_transactions": True
                }
            )

            if not isinstance(tool_resp, dict):
                raise ValueError(
                    "MCP returned an invalid checking account response."
                )

            acc_data = tool_resp.get("account")

            if not isinstance(acc_data, dict) or not acc_data:
                raise ValueError(
                    "Checking account information is missing."
                )

            # ------------------------------------------
            # 2. Validate required account information
            # ------------------------------------------

            required_fields = [
                "account_id",
                "current_balance",
                "available_balance",
                "overdraft_protection"
            ]

            for field in required_fields:
                if field not in acc_data:
                    raise ValueError(
                        f"Checking account is missing {field}."
                    )

            current_balance = self._number(
                acc_data["current_balance"],
                "current_balance"
            )

            available_balance = self._number(
                acc_data["available_balance"],
                "available_balance"
            )

            if current_balance < 0 or available_balance < 0:
                raise ValueError(
                    "Checking balances cannot be negative."
                )

            overdraft_protection = acc_data[
                "overdraft_protection"
            ]

            if not isinstance(overdraft_protection, bool):
                raise ValueError(
                    "overdraft_protection must be a boolean."
                )

            transactions = self._validate_transactions(
                tool_resp.get("transactions", [])
            )

            # ------------------------------------------
            # 3. Update shared financial state
            # ------------------------------------------

            state.checking = CheckingAccountState(
                account_id=str(acc_data["account_id"]),
                name=str(
                    acc_data.get(
                        "name",
                        "Everyday Checking Account"
                    )
                ),
                current_balance=current_balance,
                available_balance=available_balance,
                overdraft_protection=overdraft_protection,
                recent_transactions=transactions
            )

            # ------------------------------------------
            # 4. A2A communication to Cash Flow Forecaster
            # ------------------------------------------

            self.send_a2a_message(
                recipient_id="crewai_cash_flow",
                recipient_framework="CrewAI",
                recipient_role="Cash Flow Forecaster",
                topic="checking_balance_update",
                content={
                    "account_id": state.checking.account_id,
                    "current_balance": current_balance,
                    "available_balance": available_balance,
                    "overdraft_protection": overdraft_protection,
                    "transaction_count": len(transactions)
                },
                trace_id=state.trace_id,
                state_delta={
                    "checking_available": available_balance
                }
            )

            # ------------------------------------------
            # 5. Monitoring and observability
            # ------------------------------------------

            duration_ms = (
                time.time() - started_at
            ) * 1000.0

            purchase_amount = float(
                state.purchase_request.amount
            )

            sufficient_balance = (
                available_balance >= purchase_amount
            )

            summary = (
                f"Checking available: ${available_balance:,.2f}; "
                f"Current balance: ${current_balance:,.2f}; "
                f"Purchase: ${purchase_amount:,.2f}; "
                f"Sufficient available balance: "
                f"{sufficient_balance}; "
                f"Transactions: {len(transactions)}."
            )

            self.callbacks.on_state_update(
                self.name,
                "ADK",
                "state.checking",
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
                    "checking": state.checking.model_dump()
                },
                duration_ms,
                mcp_tools=["plaid_db_lookup"]
            )

            state.add_trace(
                self.name,
                "ADK",
                "Plaid Checking Lookup",
                "SUCCESS",
                (
                    "Retrieve and validate checking account "
                    f"for purchase ${purchase_amount:.2f}"
                ),
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
                f"Checking assessment failed: {exc}",
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
                "Plaid Checking Lookup",
                "FAILED",
                "Retrieve and validate checking account",
                str(exc),
                duration_ms
            )

            raise

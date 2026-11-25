
"""
Agent 4: Investment Account Watcher (Google ADK Framework).

Retrieves investment account information and market data through MCP.
Validates portfolio values, distinguishes brokerage cash from investments,
and identifies market anomalies.
"""

import math
import time

from agents.adk_framework.base import ADKDomainService
from core.state import FinGuardState, InvestmentAccountState


class InvestmentWatcherAgent(ADKDomainService):

    def __init__(self):
        super().__init__(
            agent_id="adk_investment_watcher",
            name="Investment Account Watcher",
            role="Portfolio Valuation & Market Volatility Monitor",
            instructions=(
                "Monitor portfolio value, brokerage cash, investment "
                "holdings, and market volatility. Never treat invested "
                "assets as immediately spendable cash."
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

    @classmethod
    def _validate_holdings(cls, holdings):
        if not isinstance(holdings, list):
            raise ValueError(
                "Investment holdings must be a list."
            )

        validated = []

        for index, holding in enumerate(holdings):
            if not isinstance(holding, dict):
                raise ValueError(
                    f"Invalid holding at index {index}."
                )

            symbol = holding.get("symbol")

            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError(
                    f"Holding at index {index} has no valid symbol."
                )

            # Validate numeric fields when supplied.
            for field in (
                "shares",
                "current_price",
                "market_value",
                "unrealized_gain_pct"
            ):
                if field in holding:
                    value = cls._number(
                        holding[field],
                        f"holdings[{index}].{field}"
                    )

                    if field in (
                        "shares",
                        "current_price",
                        "market_value"
                    ) and value < 0:
                        raise ValueError(
                            f"Negative {field} in holding {symbol}."
                        )

            validated.append(dict(holding))

        return validated

    @staticmethod
    def _validate_market_response(response):
        if not isinstance(response, dict):
            raise ValueError(
                "Market parser returned an invalid response."
            )

        if response.get("status") != "success":
            raise ValueError(
                "Market data retrieval failed: "
                + str(response.get("error", "Unknown market data error"))
            )

        summary = response.get("holdings_summary")
        anomalies = response.get("anomalies_detected")

        if not isinstance(summary, list):
            raise ValueError(
                "Market response holdings_summary must be a list."
            )

        if not isinstance(anomalies, list):
            raise ValueError(
                "Market response anomalies_detected must be a list."
            )

        for index, item in enumerate(summary):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Invalid market summary record at index {index}."
                )

            for field in (
                "latest_price",
                "avg_daily_change_pct",
                "max_volatility_index"
            ):
                if field not in item:
                    raise ValueError(
                        f"Market summary record is missing {field}."
                    )

                value = float(item[field])

                if not math.isfinite(value):
                    raise ValueError(
                        f"Invalid market summary value: {field}."
                    )

        for index, anomaly in enumerate(anomalies):
            if not isinstance(anomaly, dict):
                raise ValueError(
                    f"Invalid anomaly record at index {index}."
                )

            for field in (
                "symbol",
                "daily_change_pct",
                "volatility_index",
                "anomaly_flag"
            ):
                if field not in anomaly:
                    raise ValueError(
                        f"Anomaly record is missing {field}."
                    )

            for field in (
                "daily_change_pct",
                "volatility_index"
            ):
                value = float(anomaly[field])

                if not math.isfinite(value):
                    raise ValueError(
                        f"Invalid anomaly value: {field}."
                    )

        return summary, anomalies

    @staticmethod
    def _select_worst_anomaly(anomalies):
        """
        Select the highest-volatility anomaly.
        Use absolute daily movement as the tie-breaker.
        """
        if not anomalies:
            return None

        return max(
            anomalies,
            key=lambda item: (
                float(item["volatility_index"]),
                abs(float(item["daily_change_pct"]))
            )
        )

    def run(self, state: FinGuardState) -> FinGuardState:
        started_at = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "ADK",
            "Querying investment portfolio and market data"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "ADK",
            "query_investment_portfolio"
        )

        try:
            # ----------------------------------------------
            # 1. Retrieve investment account
            # ----------------------------------------------

            tool_resp = self.call_mcp_tool(
                "plaid_db_lookup",
                {
                    "account_type": "investment",
                    "include_transactions": False
                }
            )

            if not isinstance(tool_resp, dict):
                raise ValueError(
                    "MCP returned an invalid investment account response."
                )

            acc_data = tool_resp.get("account")

            if not isinstance(acc_data, dict) or not acc_data:
                raise ValueError(
                    "Investment account data is missing."
                )

            required_fields = [
                "total_portfolio_value",
                "cash_reserve"
            ]

            for field in required_fields:
                if field not in acc_data:
                    raise ValueError(
                        f"Investment account is missing {field}."
                    )

            portfolio_value = self._number(
                acc_data["total_portfolio_value"],
                "total_portfolio_value"
            )

            cash_reserve = self._number(
                acc_data["cash_reserve"],
                "cash_reserve"
            )

            if portfolio_value < 0:
                raise ValueError(
                    "Portfolio value cannot be negative."
                )

            if cash_reserve < 0:
                raise ValueError(
                    "Brokerage cash reserve cannot be negative."
                )

            if cash_reserve > portfolio_value:
                raise ValueError(
                    "Brokerage cash reserve cannot exceed portfolio value."
                )

            holdings = self._validate_holdings(
                acc_data.get("holdings", [])
            )

            # ----------------------------------------------
            # 2. Retrieve historical market data
            # ----------------------------------------------

            market_resp = self.call_mcp_tool(
                "market_data_parser",
                {
                    "symbol": "ALL",
                    "days": 5
                }
            )

            market_summary, anomalies = (
                self._validate_market_response(market_resp)
            )

            # ----------------------------------------------
            # 3. Identify the most significant anomaly
            # ----------------------------------------------

            worst_anomaly = self._select_worst_anomaly(
                anomalies
            )

            volatility_warning = None

            if worst_anomaly:
                symbol = worst_anomaly["symbol"]
                daily_change = float(
                    worst_anomaly["daily_change_pct"]
                )
                volatility_index = float(
                    worst_anomaly["volatility_index"]
                )
                anomaly_flag = worst_anomaly["anomaly_flag"]

                volatility_warning = (
                    f"Elevated market volatility detected for {symbol}: "
                    f"{daily_change:+.2f}% daily change, "
                    f"volatility index {volatility_index:.2f}, "
                    f"flag: {anomaly_flag}."
                )

            # ----------------------------------------------
            # 4. Validate portfolio holdings against market data
            # ----------------------------------------------

            market_symbols = {
                item["symbol"].strip().upper()
                for item in market_summary
                if isinstance(item.get("symbol"), str)
            }

            portfolio_symbols = {
                item["symbol"].strip().upper()
                for item in holdings
            }

            unmatched_symbols = sorted(
                portfolio_symbols - market_symbols
            )

            # ----------------------------------------------
            # 5. Update investment state
            # ----------------------------------------------

            state.investment = InvestmentAccountState(
                account_id=str(
                    acc_data.get("account_id", "acc_inv_04")
                ),
                name=str(
                    acc_data.get(
                        "name",
                        "Growth & Index Brokerage"
                    )
                ),
                total_portfolio_value=portfolio_value,
                cash_reserve=cash_reserve,
                holdings=holdings,

                # The MCP response does not provide a verified
                # portfolio-level daily unrealized return.
                daily_unrealized_change_pct=0.0,

                volatility_alert=volatility_warning
            )

            # ----------------------------------------------
            # 6. A2A notification to Risk Agent
            # ----------------------------------------------

            self.send_a2a_message(
                recipient_id="adk_risk_anomaly",
                recipient_framework="ADK",
                recipient_role="Risk & Anomaly Evaluator",
                topic="investment_market_risk",
                content={
                    "portfolio_value": portfolio_value,
                    "cash_reserve": cash_reserve,
                    "holdings_count": len(holdings),
                    "volatility_alert": volatility_warning,
                    "market_stress_flag": bool(
                        market_resp.get("market_stress_flag", False)
                    ),
                    "anomalies": anomalies,
                    "unmatched_portfolio_symbols": unmatched_symbols,
                    "daily_unrealized_change_available": False
                },
                trace_id=state.trace_id
            )

            # ----------------------------------------------
            # 7. Monitoring and observability
            # ----------------------------------------------

            duration_ms = (
                time.time() - started_at
            ) * 1000.0

            summary = (
                f"Portfolio: ${portfolio_value:,.2f}; "
                f"Brokerage Cash: ${cash_reserve:,.2f}; "
                f"Holdings: {len(holdings)}; "
                f"Market Anomalies: {len(anomalies)}; "
                f"Alert: {volatility_warning or 'None'}."
            )

            self.callbacks.on_state_update(
                self.name,
                "ADK",
                "state.investment",
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
                    "investment": state.investment.model_dump(),
                    "market_summary": market_summary,
                    "anomalies_detected": len(anomalies),
                    "unmatched_symbols": unmatched_symbols
                },
                duration_ms,
                mcp_tools=[
                    "plaid_db_lookup",
                    "market_data_parser"
                ]
            )

            state.add_trace(
                self.name,
                "ADK",
                "Investment & Market Data Lookup",
                "SUCCESS",
                "Validate portfolio and identify market anomalies",
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
                f"Investment assessment failed: {exc}",
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
                "Investment & Market Data Lookup",
                "FAILED",
                "Retrieve and validate investment and market data",
                str(exc),
                duration_ms
            )

            raise

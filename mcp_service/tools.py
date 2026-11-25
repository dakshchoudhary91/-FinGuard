
"""
FinGuard MCP Tools.

Provides:
1. Plaid mock account and transaction lookup
2. Financial affordability and runway calculations
3. Historical market data analysis

Uses Python's standard library for CSV processing.
"""

import csv
import json
import math
import os
from collections import defaultdict
from typing import Dict, Any


DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data"
)


def _validate_number(name: str, value: Any) -> float:
    """Validate a finite numeric input. Booleans are not accepted."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")

    value = float(value)

    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")

    if value < 0:
        raise ValueError(f"{name} cannot be negative.")

    return value


def tool_plaid_db_lookup(
    account_type: str = "all",
    include_transactions: bool = True
) -> Dict[str, Any]:
    """Look up simulated account balances and transactions."""

    allowed_types = {
        "checking",
        "credit_card",
        "savings",
        "investment",
        "all"
    }

    if not isinstance(account_type, str):
        return {"error": "account_type must be a string."}

    account_type = account_type.lower().strip()

    if account_type not in allowed_types:
        return {
            "error": (
                f"Invalid account_type '{account_type}'. "
                f"Supported: {', '.join(sorted(allowed_types))}."
            )
        }

    if not isinstance(include_transactions, bool):
        return {"error": "include_transactions must be a boolean."}

    db_path = os.path.join(DATA_DIR, "plaid_mock_accounts.json")

    if not os.path.isfile(db_path):
        return {"error": "Plaid mock database file was not found."}

    try:
        with open(db_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return {"error": "Plaid database must contain a JSON object."}

        accounts = data.get("accounts", {})
        transactions = data.get("recent_transactions", [])

        if not isinstance(accounts, dict):
            return {"error": "Invalid accounts structure in Plaid database."}

        if not isinstance(transactions, list):
            return {"error": "Invalid transactions structure in Plaid database."}

        result = {
            "status": "success",
            "account_type": account_type
        }

        if account_type == "all":
            result["accounts"] = accounts

            if include_transactions:
                result["transactions"] = transactions

        else:
            if account_type not in accounts:
                return {
                    "error": f"Account '{account_type}' was not found."
                }

            account = accounts[account_type]

            if not isinstance(account, dict):
                return {
                    "error": f"Invalid account record for '{account_type}'."
                }

            result["account"] = account

            if include_transactions:
                account_id = account.get("account_id")

                result["transactions"] = [
                    tx for tx in transactions
                    if isinstance(tx, dict)
                    and tx.get("account_id") == account_id
                ]

        return result

    except (OSError, json.JSONDecodeError) as exc:
        return {
            "error": f"Could not read Plaid database: {str(exc)}"
        }


def tool_financial_calculator(
    calc_type: str,
    liquid_cash: float = 0.0,
    purchase_amount: float = 0.0,
    monthly_expenses: float = 0.0,
    total_debt: float = 0.0,
    monthly_income: float = 0.0,
    emergency_target: float = 5000.0
) -> Dict[str, Any]:
    """
    Perform financial calculations.

    Supported calculations:
    - affordability_ratio
    - runway_days
    - dti_ratio
    - buffer_impact
    """

    if not isinstance(calc_type, str):
        return {"error": "calc_type must be a string."}

    calc_type = calc_type.lower().strip()

    supported_types = {
        "affordability_ratio",
        "runway_days",
        "dti_ratio",
        "buffer_impact"
    }

    if calc_type not in supported_types:
        return {
            "error": (
                f"Unknown calc_type '{calc_type}'. "
                f"Supported: {', '.join(sorted(supported_types))}."
            )
        }

    try:
        liquid_cash = _validate_number("liquid_cash", liquid_cash)
        purchase_amount = _validate_number(
            "purchase_amount", purchase_amount
        )
        monthly_expenses = _validate_number(
            "monthly_expenses", monthly_expenses
        )
        total_debt = _validate_number("total_debt", total_debt)
        monthly_income = _validate_number(
            "monthly_income", monthly_income
        )
        emergency_target = _validate_number(
            "emergency_target", emergency_target
        )

    except ValueError as exc:
        return {"error": str(exc)}

    if calc_type == "affordability_ratio":

        remaining_cash = liquid_cash - purchase_amount

        ratio = (
            remaining_cash / liquid_cash
            if liquid_cash > 0
            else 0.0
        )

        # Retention is bounded to 0-1; a negative remainder (overdraft)
        # is reported through remaining_cash / severe_deficit instead.
        ratio = max(0.0, min(1.0, ratio))

        return {
            "calc_type": calc_type,
            "liquid_cash": liquid_cash,
            "purchase_amount": purchase_amount,
            "remaining_cash": round(remaining_cash, 2),
            "liquidity_retention_ratio": round(ratio, 4),
            "is_safe": (
                ratio >= 0.50
                and remaining_cash >= 0
            ),
            "severe_deficit": remaining_cash < 0
        }

    elif calc_type == "runway_days":

        if monthly_expenses <= 0:
            return {
                "error": (
                    "monthly_expenses must be greater than zero "
                    "to calculate financial runway."
                )
            }

        daily_burn = monthly_expenses / 30.0

        post_purchase_cash = liquid_cash - purchase_amount

        current_runway_days = int(
            liquid_cash / daily_burn
        )

        post_purchase_runway_days = int(
            max(0.0, post_purchase_cash) / daily_burn
        )

        days_lost = (
            current_runway_days - post_purchase_runway_days
        )

        if post_purchase_cash < 0:
            status = "CRITICAL"
        elif post_purchase_runway_days < 7:
            status = "CRITICAL"
        elif post_purchase_runway_days < 30:
            status = "WARNING"
        else:
            status = "HEALTHY"

        return {
            "calc_type": calc_type,
            "daily_burn_rate": round(daily_burn, 2),
            "current_runway_days": current_runway_days,
            "post_purchase_runway_days": post_purchase_runway_days,
            "runway_days_lost": days_lost,
            "post_purchase_cash": round(post_purchase_cash, 2),
            "status": status
        }

    elif calc_type == "dti_ratio":

        if monthly_income <= 0:
            return {
                "calc_type": calc_type,
                "total_debt": total_debt,
                "monthly_income": monthly_income,
                "dti_percentage": None,
                "health_level": "UNDEFINED",
                "error": (
                    "Monthly income must be greater than zero "
                    "to calculate the debt-to-income ratio."
                )
            }

        dti = (
            total_debt / monthly_income
        ) * 100.0

        if dti < 36.0:
            health_level = "GOOD"
        elif dti <= 43.0:
            health_level = "CONCERNING"
        else:
            health_level = "DANGEROUS"

        return {
            "calc_type": calc_type,
            "total_debt": total_debt,
            "monthly_income": monthly_income,
            "dti_percentage": round(dti, 2),
            "health_level": health_level
        }

    elif calc_type == "buffer_impact":

        # Preserve negative balances rather than hiding deficits.
        post_purchase_liquid = liquid_cash - purchase_amount

        reserve_deficit = max(
            0.0,
            emergency_target - post_purchase_liquid
        )

        cushion_ratio = (
            post_purchase_liquid / emergency_target
            if emergency_target > 0
            else None
        )

        return {
            "calc_type": calc_type,
            "emergency_target": emergency_target,
            "post_purchase_liquid": round(
                post_purchase_liquid, 2
            ),
            "reserve_deficit": round(reserve_deficit, 2),
            "cushion_coverage_pct": (
                round(cushion_ratio * 100.0, 1)
                if cushion_ratio is not None
                else None
            ),
            "floor_breached": (
                post_purchase_liquid < emergency_target
            ),
            "negative_balance": post_purchase_liquid < 0
        }


def tool_market_data_parser(
    symbol: str = "ALL",
    days: int = 5
) -> Dict[str, Any]:
    """
    Analyze historical market data from CSV.

    Expected columns:
    symbol, price, daily_change_pct,
    volatility_index, anomaly_flag
    """

    if not isinstance(symbol, str) or not symbol.strip():
        return {"error": "symbol must be a non-empty string."}

    if isinstance(days, bool) or not isinstance(days, int):
        return {"error": "days must be an integer."}

    if days < 1 or days > 365:
        return {"error": "days must be between 1 and 365."}

    symbol = symbol.upper().strip()

    csv_path = os.path.join(
        DATA_DIR,
        "historical_market_data.csv"
    )

    if not os.path.isfile(csv_path):
        return {"error": "Historical market data CSV was not found."}

    required_columns = {
        "symbol",
        "price",
        "daily_change_pct",
        "volatility_index",
        "anomaly_flag"
    }

    try:
        with open(
            csv_path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            if not reader.fieldnames:
                return {"error": "Market CSV has no header row."}

            missing = required_columns - set(reader.fieldnames)

            if missing:
                return {
                    "error": (
                        "Market CSV is missing required columns: "
                        + ", ".join(sorted(missing))
                    )
                }

            records = list(reader)

        if not records:
            return {"error": "Market CSV contains no data."}

        if symbol != "ALL":
            records = [
                row for row in records
                if row["symbol"].strip().upper() == symbol
            ]

            if not records:
                return {
                    "error": f"Symbol '{symbol}' was not found."
                }

        # Preserve the original file-order assumption:
        # records are expected to be ordered oldest to newest.
        if symbol == "ALL":
            grouped = defaultdict(list)

            for row in records:
                grouped[row["symbol"].strip().upper()].append(row)

            recent_records = []

            for rows in grouped.values():
                recent_records.extend(rows[-days:])

        else:
            recent_records = records[-days:]

        anomalies = []
        grouped_recent = defaultdict(list)

        for row in recent_records:

            try:
                price = float(row["price"])
                change = float(row["daily_change_pct"])
                volatility = float(row["volatility_index"])

                if not all(
                    math.isfinite(value)
                    for value in (price, change, volatility)
                ):
                    raise ValueError("Non-finite market value.")

                if price < 0 or volatility < 0:
                    raise ValueError("Negative market value.")

            except (TypeError, ValueError):
                return {
                    "error": (
                        "Market CSV contains invalid numeric data."
                    )
                }

            normalized = {
                **row,
                "symbol": row["symbol"].strip().upper(),
                "price": price,
                "daily_change_pct": change,
                "volatility_index": volatility
            }

            grouped_recent[normalized["symbol"]].append(normalized)

            if row["anomaly_flag"].strip().upper() != "NORMAL":
                anomalies.append(normalized)

        summary = []

        for sym, rows in grouped_recent.items():

            latest_price = rows[-1]["price"]

            avg_change = sum(
                row["daily_change_pct"]
                for row in rows
            ) / len(rows)

            max_volatility = max(
                row["volatility_index"]
                for row in rows
            )

            has_warnings = any(
                row["anomaly_flag"].strip().upper() != "NORMAL"
                for row in rows
            )

            summary.append({
                "symbol": sym,
                "latest_price": latest_price,
                "avg_daily_change_pct": round(avg_change, 2),
                "max_volatility_index": max_volatility,
                "has_warnings": has_warnings
            })

        return {
            "status": "success",
            "symbol_queried": symbol,
            "total_records_examined": len(recent_records),
            "holdings_summary": summary,
            "anomalies_detected": anomalies,
            "market_stress_flag": len(anomalies) > 0
        }

    except OSError as exc:
        return {
            "error": f"Could not read market data: {str(exc)}"
        }

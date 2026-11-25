
"""
FinGuard Security and Integrity Guardrails.

Provides:
- Prompt injection detection
- Input validation
- MCP tool output validation
- Financial data integrity checks
- Mathematical liquidity invariants
"""

import math
import re

from typing import Dict, Any, Tuple, Optional, List


class SecurityViolation(Exception):
    """Raised when a security or financial integrity violation occurs."""


class FinGuardGuardrails:

    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"disregard\s+(all\s+)?(rules|prompts|constraints)",
        r"you\s+are\s+now\s+(in\s+developer\s+mode|dan|an\s+unrestricted)",
        r"system\s*prompt\s*reveal",
        r"print\s+your\s+instructions",
        r"override\s+(my\s+)?(balance|budget|limits?)",
        r"force\s+approval",
        r"approve\s+this\s+purchase\s+no\s+matter\s+what",
        r"transfer\s+(?:\$?\d+(?:\.\d{1,2})?|\w+)\s+to",
        r"<script\s*[^>]*>",
        r"javascript\s*:",
        r"onerror\s*=",
        r"\bsudo\b",
        r"\brm\s+-rf\b",
        r"\bdrop\s+table\b",
    ]

    TOXIC_PATTERNS = [
        r"\b(idiot|stupid|moron|dumb|kill\s+yourself|fuck|shit|bitch|bastard)\b"
    ]

    VALID_CALC_TYPES = {
        "affordability_ratio",
        "runway_days",
        "dti_ratio",
        "buffer_impact",
    }

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        """Return True for finite numeric values, excluding booleans."""

        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )

    @classmethod
    def validate_user_input(
        cls,
        user_text: str,
        amount: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Validate user input for injection patterns, abusive language
        and invalid purchase amounts.
        """

        if not isinstance(user_text, str) or not user_text.strip():
            return False, "Input prompt cannot be empty."

        text_clean = user_text.lower().strip()

        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, text_clean, re.IGNORECASE):
                return (
                    False,
                    "SECURITY VIOLATION: Potential prompt injection "
                    "or unsafe instruction detected."
                )

        for pattern in cls.TOXIC_PATTERNS:
            if re.search(pattern, text_clean, re.IGNORECASE):
                return (
                    False,
                    "COMMUNICATION POLICY VIOLATION: Abusive language "
                    "detected. Please use professional language."
                )

        if amount is not None:

            if not cls._is_finite_number(amount):
                return (
                    False,
                    "INVALID PURCHASE: Amount must be a finite number."
                )

            if amount <= 0:
                return (
                    False,
                    "INVALID PURCHASE: Amount must be greater than zero."
                )

            if amount > 10_000_000:
                return (
                    False,
                    "OUT-OF-BOUNDS: Purchase amount exceeds "
                    "the evaluation ceiling of 10,000,000."
                )

        return True, "Input cleared security guardrails."

    @classmethod
    def _validate_account(
        cls,
        account: Any,
        account_name: str
    ) -> Tuple[bool, str]:

        if not isinstance(account, dict):
            return False, (
                f"Plaid validation failure: {account_name} "
                "must be an object."
            )

        balance = account.get(
            "current_balance",
            account.get("total_portfolio_value")
        )

        if not cls._is_finite_number(balance):
            return False, (
                f"Plaid validation failure: {account_name} "
                "has a missing or invalid balance."
            )

        return True, "Account passed validation."

    @classmethod
    def validate_tool_output(
        cls,
        tool_name: str,
        raw_output: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Validate the response structures of FinGuard MCP tools.
        """

        if not isinstance(raw_output, dict):
            return False, (
                f"Tool '{tool_name}' must return a dictionary."
            )

        if raw_output.get("isError") is True:
            return False, (
                f"Tool '{tool_name}' reported an error: "
                f"{raw_output.get('error', 'Unknown tool error')}"
            )

        if "error" in raw_output:
            return False, (
                f"Tool '{tool_name}' returned an error: "
                f"{raw_output['error']}"
            )

        if tool_name == "plaid_db_lookup":

            if raw_output.get("status") != "success":
                return False, (
                    "Plaid validation failure: missing success status."
                )

            if "accounts" in raw_output:
                accounts = raw_output["accounts"]

                if not isinstance(accounts, dict) or not accounts:
                    return False, (
                        "Plaid validation failure: accounts must be "
                        "a non-empty dictionary."
                    )

                for name, account in accounts.items():
                    valid, message = cls._validate_account(
                        account,
                        str(name)
                    )

                    if not valid:
                        return False, message

            elif "account" in raw_output:
                valid, message = cls._validate_account(
                    raw_output["account"],
                    "account"
                )

                if not valid:
                    return False, message

            else:
                return False, (
                    "Plaid validation failure: no account data returned."
                )

            if "transactions" in raw_output:
                if not isinstance(raw_output["transactions"], list):
                    return False, (
                        "Plaid validation failure: transactions "
                        "must be a list."
                    )

                for transaction in raw_output["transactions"]:
                    if not isinstance(transaction, dict):
                        return False, (
                            "Plaid validation failure: invalid transaction "
                            "record."
                        )

            return True, "Plaid output passed validation."

        elif tool_name == "financial_calculator":

            calc_type = raw_output.get("calc_type")

            if calc_type not in cls.VALID_CALC_TYPES:
                return False, (
                    "Calculator validation failure: invalid or missing "
                    "calc_type."
                )

            required_fields = {
                "affordability_ratio": [
                    "liquid_cash",
                    "purchase_amount",
                    "remaining_cash",
                    "liquidity_retention_ratio",
                    "is_safe",
                    "severe_deficit",
                ],
                "runway_days": [
                    "daily_burn_rate",
                    "current_runway_days",
                    "post_purchase_runway_days",
                    "runway_days_lost",
                    "post_purchase_cash",
                    "status",
                ],
                "dti_ratio": [
                    "total_debt",
                    "monthly_income",
                    "dti_percentage",
                    "health_level",
                ],
                "buffer_impact": [
                    "emergency_target",
                    "post_purchase_liquid",
                    "reserve_deficit",
                    "cushion_coverage_pct",
                    "floor_breached",
                    "negative_balance",
                ],
            }

            for field in required_fields[calc_type]:
                if field not in raw_output:
                    return False, (
                        f"Calculator validation failure: missing "
                        f"'{field}'."
                    )

            numeric_fields = {
                "affordability_ratio": [
                    "liquid_cash",
                    "purchase_amount",
                    "remaining_cash",
                    "liquidity_retention_ratio",
                ],
                "runway_days": [
                    "daily_burn_rate",
                    "current_runway_days",
                    "post_purchase_runway_days",
                    "runway_days_lost",
                    "post_purchase_cash",
                ],
                "dti_ratio": [
                    "total_debt",
                    "monthly_income",
                ],
                "buffer_impact": [
                    "emergency_target",
                    "post_purchase_liquid",
                    "reserve_deficit",
                ],
            }

            for field in numeric_fields[calc_type]:
                if not cls._is_finite_number(raw_output[field]):
                    return False, (
                        f"Calculator validation failure: '{field}' "
                        "must be a finite number."
                    )

            if calc_type == "dti_ratio":
                dti = raw_output["dti_percentage"]

                if dti is not None and not cls._is_finite_number(dti):
                    return False, (
                        "Calculator validation failure: invalid DTI."
                    )

                if dti is None and raw_output["health_level"] != "UNDEFINED":
                    return False, (
                        "Calculator validation failure: undefined DTI "
                        "must have UNDEFINED health level."
                    )

            if calc_type in {
                "affordability_ratio",
                "buffer_impact",
            }:
                boolean_fields = (
                    ["is_safe", "severe_deficit"]
                    if calc_type == "affordability_ratio"
                    else ["floor_breached", "negative_balance"]
                )

                for field in boolean_fields:
                    if not isinstance(raw_output[field], bool):
                        return False, (
                            f"Calculator validation failure: "
                            f"'{field}' must be boolean."
                        )

            return True, "Calculator output passed validation."

        elif tool_name == "market_data_parser":

            if raw_output.get("status") != "success":
                return False, (
                    "Market parser validation failure: "
                    "missing success status."
                )

            if not isinstance(raw_output.get("symbol_queried"), str):
                return False, (
                    "Market parser validation failure: invalid symbol."
                )

            if not cls._is_finite_number(
                raw_output.get("total_records_examined")
            ):
                return False, (
                    "Market parser validation failure: invalid "
                    "record count."
                )

            if raw_output["total_records_examined"] < 0:
                return False, "Market parser validation failure: negative record count."

            summary = raw_output.get("holdings_summary")
            anomalies = raw_output.get("anomalies_detected")

            if not isinstance(summary, list):
                return False, (
                    "Market parser validation failure: holdings_summary "
                    "must be a list."
                )

            if not isinstance(anomalies, list):
                return False, (
                    "Market parser validation failure: anomalies_detected "
                    "must be a list."
                )

            for item in summary:
                if not isinstance(item, dict):
                    return False, "Invalid market summary record."

                for field in (
                    "symbol",
                    "latest_price",
                    "avg_daily_change_pct",
                    "max_volatility_index",
                    "has_warnings",
                ):
                    if field not in item:
                        return False, (
                            f"Market summary missing '{field}'."
                        )

                for field in (
                    "latest_price",
                    "avg_daily_change_pct",
                    "max_volatility_index",
                ):
                    if not cls._is_finite_number(item[field]):
                        return False, (
                            f"Market summary has invalid '{field}'."
                        )

                if not isinstance(item["has_warnings"], bool):
                    return False, (
                        "Market summary has invalid warning flag."
                    )

            if not isinstance(raw_output.get("market_stress_flag"), bool):
                return False, (
                    "Market parser validation failure: invalid stress flag."
                )

            return True, "Market data output passed validation."

        return False, (
            f"No output validation schema exists for tool '{tool_name}'."
        )

    @classmethod
    def enforce_mathematical_invariants(
        cls,
        verdict: str,
        checking_balance: float,
        purchase_amount: float,
        rent_due_days: int,
        rent_amount: float
    ) -> Tuple[str, List[str]]:
        """
        Enforce basic liquidity and rent-payment invariants.

        This checks the supplied checking balance and rent obligation.
        It does not replace a full upcoming-bills cash-flow analysis.
        """

        values = {
            "checking_balance": checking_balance,
            "purchase_amount": purchase_amount,
            "rent_amount": rent_amount,
        }

        for name, value in values.items():
            if not cls._is_finite_number(value):
                raise SecurityViolation(
                    f"{name} must be a finite number."
                )

        if (
            isinstance(rent_due_days, bool)
            or not isinstance(rent_due_days, int)
        ):
            raise SecurityViolation(
                "rent_due_days must be an integer."
            )

        if purchase_amount < 0 or rent_amount < 0:
            raise SecurityViolation(
                "Purchase and rent amounts cannot be negative."
            )

        warnings = []

        projected_liquid = checking_balance - purchase_amount

        if rent_due_days < 0:
            warnings.append(
                "Rent due date is in the past or has invalid timing. "
                "Verify the rent due date."
            )

        elif rent_due_days <= 3 and rent_amount > projected_liquid:

            shortfall = rent_amount - projected_liquid

            warnings.append(
                f"MATHEMATICAL INVARIANT ENFORCED: Rent of "
                f"{rent_amount:,.2f} is due in {rent_due_days} days. "
                f"Post-purchase liquid cash would be "
                f"{projected_liquid:,.2f}, leaving a shortfall of "
                f"{shortfall:,.2f}."
            )

            if verdict in (
                "CAN_AFFORD",
                "CONDITIONAL_AFFORD",
            ):
                verdict = "CANNOT_AFFORD"

        if projected_liquid < 0:

            warnings.append(
                f"LIQUIDITY FLOOR ENFORCED: Purchase would reduce "
                f"checking balance to {projected_liquid:,.2f}."
            )

            verdict = "CRITICAL_DEFICIT"

        return verdict, warnings

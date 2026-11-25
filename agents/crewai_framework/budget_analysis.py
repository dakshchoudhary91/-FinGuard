
"""
Agent 8: Budget Analysis Agent (CrewAI Framework).

Validates category budgets, checks the budget period, and evaluates
the effect of a proposed purchase without inventing missing figures.
"""

import json
import logging
import math
import os
import time
from datetime import date

from agents.crewai_framework.crew_bridge import CrewAIDomainService
from core.state import FinGuardState, BudgetAnalysisState


logger = logging.getLogger("FinGuard_Budget")

DATA_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)
BUDGET_FILE = os.path.join(DATA_DIR, "data", "budget_categories.json")


class BudgetAnalysisAgent(CrewAIDomainService):

    def __init__(self):
        super().__init__(
            agent_id="crewai_budget_analysis",
            name="Budget Analysis Agent",
            role="Monthly Category Budget & Overspending Tracker",
            goal=(
                "Evaluate a proposed purchase against validated, "
                "current monthly category budgets."
            ),
            backstory=(
                "A financial planner using envelope-budgeting principles. "
                "Distinguishes current budget data from stale or missing records."
            )
        )

    @staticmethod
    def _validate_amount(value, field_name):
        """Validate a monetary value."""
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be numeric.")

        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be numeric.")

        if not math.isfinite(amount) or amount < 0:
            raise ValueError(
                f"{field_name} must be a finite, non-negative amount."
            )

        return amount

    @staticmethod
    def _normalize_category(value):
        """Normalize category text for exact matching."""
        return " ".join(str(value or "").strip().casefold().split())

    def _load_budget_data(self):
        """Load and validate the budget JSON."""
        if not os.path.isfile(BUDGET_FILE):
            raise FileNotFoundError(
                f"Budget file not found: {BUDGET_FILE}"
            )

        with open(BUDGET_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Budget file must contain a JSON object.")

        budget_month = data.get("month")
        if not isinstance(budget_month, str):
            raise ValueError("Budget month is missing or invalid.")

        try:
            date.fromisoformat(budget_month + "-01")
        except ValueError as exc:
            raise ValueError(
                "Budget month must use YYYY-MM format."
            ) from exc

        categories = data.get("categories")

        if not isinstance(categories, dict):
            raise ValueError(
                "Budget file must contain a categories object."
            )

        if not categories:
            raise ValueError("No budget categories were found.")

        # Demo data: treat the sample budget as belonging to the current
        # month so it never goes stale. Set FINGUARD_REBASE_DEMO_DATES=false
        # to enforce the month written in budget_categories.json.
        if os.getenv(
            "FINGUARD_REBASE_DEMO_DATES", "true"
        ).strip().lower() not in {"false", "0", "no"}:
            budget_month = date.today().strftime("%Y-%m")

        return budget_month, categories

    def _find_category(self, categories, requested_category):
        """Find an exact category match, ignoring case and extra spaces."""
        requested = self._normalize_category(requested_category)

        if not requested:
            return None, None

        matches = [
            (name, values)
            for name, values in categories.items()
            if self._normalize_category(name) == requested
        ]

        if len(matches) > 1:
            raise ValueError(
                f"Multiple budget categories match '{requested_category}'."
            )

        if not matches:
            return None, None

        return matches[0]

    def run(self, state: FinGuardState) -> FinGuardState:
        t0 = time.time()

        category = str(
            state.purchase_request.category or ""
        ).strip()

        purchase_amount = self._validate_amount(
            state.purchase_request.amount,
            "Purchase amount"
        )

        self.callbacks.on_agent_start(
            self.name,
            "CrewAI",
            f"Checking budget for category: {category or 'Unspecified'}"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "CrewAI",
            "analyze_budget"
        )

        try:
            # --------------------------------------------------
            # 1. Load budget data
            # --------------------------------------------------
            budget_month, categories = self._load_budget_data()

            matched_name, matched_data = self._find_category(
                categories,
                category
            )

            current_month = date.today().strftime("%Y-%m")

            # --------------------------------------------------
            # 2. Handle missing category
            # --------------------------------------------------
            if matched_data is None:
                state.budget_analysis = BudgetAnalysisState(
                    category=category or "Unspecified",
                    monthly_limit=0.0,
                    spent_to_date=0.0,
                    remaining_budget=0.0,
                    exceeds_budget_if_purchased=False,
                    projected_overage_amount=0.0,
                    category_status="UNKNOWN_CATEGORY"
                )

                summary = (
                    f"No exact budget category found for '{category}'. "
                    "Budget impact cannot be determined."
                )

                budget_available = False
                exceeds = False
                overage = 0.0
                limit = 0.0
                spent = 0.0
                remaining = 0.0
                result_category = category or "Unspecified"

            else:
                # ----------------------------------------------
                # 3. Validate category figures
                # ----------------------------------------------
                if not isinstance(matched_data, dict):
                    raise ValueError(
                        f"Budget category '{matched_name}' must be an object."
                    )

                limit = self._validate_amount(
                    matched_data.get("monthly_limit"),
                    f"{matched_name}.monthly_limit"
                )

                spent = self._validate_amount(
                    matched_data.get("spent_to_date"),
                    f"{matched_name}.spent_to_date"
                )

                if spent > limit:
                    raise ValueError(
                        f"Spent amount for '{matched_name}' exceeds "
                        "its monthly limit. Check the budget data."
                    )

                calculated_remaining = round(limit - spent, 2)

                if "remaining" in matched_data:
                    supplied_remaining = self._validate_amount(
                        matched_data["remaining"],
                        f"{matched_name}.remaining"
                    )

                    if abs(
                        supplied_remaining - calculated_remaining
                    ) > 0.02:
                        raise ValueError(
                            f"Inconsistent remaining budget for "
                            f"'{matched_name}'. Expected "
                            f"{calculated_remaining:.2f}, received "
                            f"{supplied_remaining:.2f}."
                        )

                remaining = calculated_remaining
                result_category = matched_name

                # ----------------------------------------------
                # 4. Reject stale budget periods for decisions
                # ----------------------------------------------
                if budget_month != current_month:
                    exceeds = False
                    overage = 0.0

                    state.budget_analysis = BudgetAnalysisState(
                        category=result_category,
                        monthly_limit=limit,
                        spent_to_date=spent,
                        remaining_budget=remaining,
                        exceeds_budget_if_purchased=False,
                        projected_overage_amount=0.0,
                        category_status="STALE_BUDGET"
                    )

                    budget_available = False

                    summary = (
                        f"Budget data is for {budget_month}, but the "
                        f"current month is {current_month}. "
                        f"Historical limit: ${limit:,.2f} | "
                        f"Historical spending: ${spent:,.2f}. "
                        "Purchase impact was not evaluated."
                    )

                else:
                    # ------------------------------------------
                    # 5. Evaluate current budget
                    # ------------------------------------------
                    projected_spending = spent + purchase_amount

                    exceeds = projected_spending > limit

                    overage = round(
                        max(0.0, projected_spending - limit),
                        2
                    )

                    remaining_after_purchase = (
                        limit - projected_spending
                    )

                    if exceeds:
                        category_status = "OVER_BUDGET"

                    elif limit == 0:
                        category_status = "NO_BUDGET"

                    elif remaining_after_purchase <= 0:
                        category_status = "BUDGET_EXHAUSTED"

                    elif (
                        remaining_after_purchase / limit
                    ) <= 0.10:
                        category_status = "CRITICAL_LOW"

                    elif (
                        remaining_after_purchase / limit
                    ) <= 0.20:
                        category_status = "WARNING"

                    else:
                        category_status = "ON_TRACK"

                    state.budget_analysis = BudgetAnalysisState(
                        category=result_category,
                        monthly_limit=round(limit, 2),
                        spent_to_date=round(spent, 2),
                        remaining_budget=round(remaining, 2),
                        exceeds_budget_if_purchased=exceeds,
                        projected_overage_amount=overage,
                        category_status=category_status
                    )

                    budget_available = True

                    summary = (
                        f"Category: {result_category} | "
                        f"Limit: ${limit:,.2f} | "
                        f"Spent: ${spent:,.2f} | "
                        f"Remaining: ${remaining:,.2f} | "
                        f"Purchase: ${purchase_amount:,.2f} | "
                        f"Exceeds: {exceeds} | "
                        f"Overage: ${overage:,.2f} | "
                        f"Status: {category_status}"
                    )

            # --------------------------------------------------
            # 6. Send A2A budget information
            # --------------------------------------------------
            self.send_a2a_message(
                recipient_id="crewai_affordability",
                recipient_framework="CrewAI",
                recipient_role="Affordability Evaluator",
                topic="category_budget_verdict",
                content={
                    "category": result_category,
                    "budget_month": budget_month,
                    "current_month": current_month,
                    "budget_available": budget_available,
                    "monthly_limit": round(limit, 2),
                    "spent": round(spent, 2),
                    "remaining": round(remaining, 2),
                    "purchase_amount": round(purchase_amount, 2),
                    "exceeds": exceeds,
                    "overage": overage,
                    "status": state.budget_analysis.category_status
                },
                trace_id=state.trace_id,
                state_delta={
                    "budget_exceeded": exceeds,
                    "budget_available": budget_available
                }
            )

            # --------------------------------------------------
            # 7. Record execution
            # --------------------------------------------------
            duration_ms = (time.time() - t0) * 1000.0

            self.callbacks.on_state_update(
                self.name,
                "CrewAI",
                "state.budget_analysis",
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
                    "budget_analysis": (
                        state.budget_analysis.model_dump()
                    ),
                    "budget_month": budget_month,
                    "budget_available": budget_available
                },
                duration_ms
            )

            state.add_trace(
                self.name,
                "CrewAI",
                "Category Budget Evaluation",
                "SUCCESS",
                f"Checked budget for {result_category}",
                summary,
                duration_ms
            )

            return state

        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000.0

            logger.exception("Budget analysis failed.")

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
                "Category Budget Evaluation",
                "ERROR",
                "Budget analysis failed",
                str(exc),
                duration_ms
            )

            raise

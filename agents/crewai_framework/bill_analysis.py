
"""
Agent 7: Bill Analysis Agent (CrewAI Framework).

Tracks recurring obligations, overdue bills, and future due dates.
Calculates mandatory expenses across 7-day and 30-day horizons.
Keeps unpaid overdue bills separate from future recurring occurrences.
"""

import calendar
import json
import logging
import math
import os
import time

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from agents.crewai_framework.crew_bridge import CrewAIDomainService
from core.state import FinGuardState, BillAnalysisState


logger = logging.getLogger("FinGuard_BillAnalysis")

DATA_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    ),
    "data"
)

BILLS_FILE = os.path.join(DATA_DIR, "recurring_bills.json")

# The demo bill dates in recurring_bills.json were authored on this date
# (rent due in 3 days). When REBASE is on, due dates are shifted by the
# gap between today and this anchor so the demo never goes stale.
# Set FINGUARD_REBASE_DEMO_DATES=false to use the dates exactly as written.
# FINGUARD_DEMO_RENT_DUE_IN_DAYS controls how far away the sample rent bill is
# (default 3 days, matching the "Rent Collision" scenario).
DEMO_DATA_ANCHOR = date(2026, 10, 30) - timedelta(
    days=int(os.getenv("FINGUARD_DEMO_RENT_DUE_IN_DAYS", "3"))
)
REBASE_DEMO_DATES = os.getenv(
    "FINGUARD_REBASE_DEMO_DATES", "true"
).strip().lower() not in {"false", "0", "no"}

VALID_STATUSES = {"pending", "scheduled", "paid"}
VALID_RECURRENCES = {"monthly", "none", "yearly"}


def _parse_date(value: Any, bill_id: str) -> date:
    """Parse and validate an ISO-format bill due date."""

    if not isinstance(value, str):
        raise ValueError(
            f"Bill '{bill_id}' has an invalid due_date. "
            "Expected YYYY-MM-DD."
        )

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Bill '{bill_id}' has invalid due_date '{value}'."
        ) from exc


def _add_months(original_date: date, months: int = 1) -> date:
    """Add months while safely handling month-end dates."""

    month_index = original_date.month - 1 + months

    year = original_date.year + month_index // 12
    month = month_index % 12 + 1

    day = min(
        original_date.day,
        calendar.monthrange(year, month)[1]
    )

    return date(year, month, day)


def _add_year(original_date: date) -> date:
    """Add one year while handling leap-day dates."""

    try:
        return original_date.replace(year=original_date.year + 1)
    except ValueError:
        return original_date.replace(
            year=original_date.year + 1,
            day=28
        )



def _next_occurrence(
    due_date: date,
    recurrence: str,
    today: date
) -> Optional[date]:
    """
    Return the next recurring occurrence without duplicating
    the original bill record.

    If the original due date is in the future, advance once.
    If it is today or overdue, advance until the date is
    strictly after today.
    """

    if recurrence == "none":
        return None

    if recurrence not in {"monthly", "yearly"}:
        raise ValueError(f"Unsupported recurrence: {recurrence}")

    next_date = due_date

    def advance(current_date: date) -> date:
        if recurrence == "monthly":
            return _add_months(current_date)
        return _add_year(current_date)

    if next_date > today:
        next_date = advance(next_date)

    while next_date <= today:
        next_date = advance(next_date)

    return next_date


def _load_bills() -> List[Dict[str, Any]]:
    """Load and validate recurring bill records."""

    if not os.path.exists(BILLS_FILE):
        raise FileNotFoundError(
            f"Recurring bills file not found: {BILLS_FILE}"
        )

    try:
        with open(BILLS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {BILLS_FILE}: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise ValueError(
            "recurring_bills.json must contain a JSON list."
        )

    validated = []
    seen_ids = set()

    for index, bill in enumerate(data):
        if not isinstance(bill, dict):
            raise ValueError(
                f"Bill at index {index} must be a JSON object."
            )

        bill_id = bill.get("bill_id")

        if not isinstance(bill_id, str) or not bill_id.strip():
            raise ValueError(
                f"Bill at index {index} is missing a valid bill_id."
            )

        if bill_id in seen_ids:
            raise ValueError(
                f"Duplicate bill_id detected: {bill_id}"
            )

        seen_ids.add(bill_id)

        due_date = _parse_date(
            bill.get("due_date"),
            bill_id
        )

        if REBASE_DEMO_DATES:
            due_date = due_date + (
                datetime.now().date() - DEMO_DATA_ANCHOR
            )

        try:
            amount = float(bill.get("amount"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Bill '{bill_id}' has an invalid amount."
            ) from exc

        if not math.isfinite(amount) or amount < 0:
            raise ValueError(
                f"Bill '{bill_id}' must have a finite, non-negative amount."
            )

        status = str(
            bill.get("status", "pending")
        ).strip().lower()

        if status not in VALID_STATUSES:
            raise ValueError(
                f"Bill '{bill_id}' has unsupported status '{status}'. "
                f"Allowed values: {sorted(VALID_STATUSES)}"
            )

        recurrence = str(
            bill.get("recurrence", "none")
        ).strip().lower()

        if recurrence not in VALID_RECURRENCES:
            raise ValueError(
                f"Bill '{bill_id}' has unsupported recurrence "
                f"'{recurrence}'. Allowed values: "
                f"{sorted(VALID_RECURRENCES)}"
            )

        mandatory = bill.get("mandatory", False)

        if not isinstance(mandatory, bool):
            raise ValueError(
                f"Bill '{bill_id}' must have a boolean mandatory field."
            )

        validated_bill = dict(bill)

        validated_bill["amount"] = amount
        validated_bill["status"] = status
        validated_bill["recurrence"] = recurrence
        validated_bill["mandatory"] = mandatory
        validated_bill["_parsed_due_date"] = due_date
        validated_bill["due_date"] = due_date.isoformat()

        validated.append(validated_bill)

    return validated


def _classify_bill(
    due_date: date,
    today: date,
    paid: bool,
    mandatory: bool
) -> str:
    """Classify a bill without changing its original payment status."""

    days_remaining = (due_date - today).days

    if not mandatory:
        return "NON_MANDATORY"

    if paid:
        return "PAID"

    if days_remaining < 0:
        return "OVERDUE"

    if days_remaining == 0:
        return "DUE_TODAY"

    if days_remaining <= 7:
        return "DUE_SOON"

    if days_remaining <= 30:
        return "UPCOMING"

    return "FUTURE"


class BillAnalysisAgent(CrewAIDomainService):

    def __init__(self):
        super().__init__(
            agent_id="crewai_bill_analysis",
            name="Bill Analysis Agent",
            role="Upcoming Obligations & Recurring Due-Date Tracker",
            goal=(
                "Identify overdue obligations, upcoming mandatory bills, "
                "and shortfall risks across 7-day and 30-day horizons."
            ),
            backstory=(
                "A meticulous financial auditor specializing in timing "
                "cash outlays against fixed deadlines. Ensures essential "
                "obligations are considered before discretionary purchases."
            )
        )

    def run(self, state: FinGuardState) -> FinGuardState:

        t0 = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "CrewAI",
            "Analyzing overdue bills and upcoming mandatory commitments"
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "CrewAI",
            "analyze_bills"
        )

        try:
            today = datetime.now().date()

            bills_data = _load_bills()

            # --------------------------------------------------
            # 1. Classify original bill occurrences
            # --------------------------------------------------

            enriched_bills = []

            mandatory_overdue = []
            mandatory_upcoming_7d = []
            mandatory_upcoming_30d = []

            for bill in bills_data:

                due_date = bill["_parsed_due_date"]
                amount = bill["amount"]
                mandatory = bill["mandatory"]
                paid = bill["status"] == "paid"
                recurrence = bill["recurrence"]

                days_remaining = (due_date - today).days

                computed_status = _classify_bill(
                    due_date=due_date,
                    today=today,
                    paid=paid,
                    mandatory=mandatory
                )

                record = {
                    key: value
                    for key, value in bill.items()
                    if key != "_parsed_due_date"
                }

                record["days_until_due"] = days_remaining
                record["computed_status"] = computed_status
                record["occurrence_type"] = "original"
                record["is_overdue"] = (
                    mandatory and not paid and days_remaining < 0
                )

                enriched_bills.append(record)

                if not mandatory or paid:
                    continue

                if days_remaining < 0:
                    mandatory_overdue.append(record)

                elif days_remaining <= 7:
                    mandatory_upcoming_7d.append(record)
                    mandatory_upcoming_30d.append(record)

                elif days_remaining <= 30:
                    mandatory_upcoming_30d.append(record)

            # --------------------------------------------------
            # 2. Generate separate future recurring occurrences
            # --------------------------------------------------

            for bill in bills_data:

                recurrence = bill["recurrence"]

                if recurrence == "none":
                    continue

                original_due_date = bill["_parsed_due_date"]

                future_due_date = _next_occurrence(
                    due_date=original_due_date,
                    recurrence=recurrence,
                    today=today
                )

                if future_due_date is None:
                    continue

                days_remaining = (future_due_date - today).days

                # Avoid duplicating distant occurrences that do not
                # contribute to either reporting horizon.
                if days_remaining > 30:
                    continue

                mandatory = bill["mandatory"]

                future_record = {
                    key: value
                    for key, value in bill.items()
                    if key != "_parsed_due_date"
                }

                future_record["bill_id"] = (
                    f"{bill['bill_id']}_next_occurrence"
                )

                future_record["due_date"] = (
                    future_due_date.isoformat()
                )

                future_record["days_until_due"] = days_remaining
                future_record["status"] = "scheduled"
                future_record["computed_status"] = _classify_bill(
                    due_date=future_due_date,
                    today=today,
                    paid=False,
                    mandatory=mandatory
                )

                future_record["occurrence_type"] = "next_recurring"
                future_record["is_overdue"] = False
                future_record["source_bill_id"] = bill["bill_id"]

                enriched_bills.append(future_record)

                if not mandatory:
                    continue

                if days_remaining <= 7:
                    mandatory_upcoming_7d.append(future_record)
                    mandatory_upcoming_30d.append(future_record)

                elif days_remaining <= 30:
                    mandatory_upcoming_30d.append(future_record)

            # --------------------------------------------------
            # 3. Calculate mandatory obligation totals
            # --------------------------------------------------

            total_overdue = sum(
                bill["amount"]
                for bill in mandatory_overdue
            )

            total_7d = sum(
                bill["amount"]
                for bill in mandatory_upcoming_7d
            )

            total_30d = sum(
                bill["amount"]
                for bill in mandatory_upcoming_30d
            )

            # --------------------------------------------------
            # 4. Identify the next outstanding mandatory bill
            # --------------------------------------------------

            outstanding_mandatory = [
                bill
                for bill in enriched_bills
                if bill["mandatory"]
                and bill["status"] != "paid"
                and bill["computed_status"] != "PAID"
                and bill["occurrence_type"] in (
                    "original",
                    "next_recurring"
                )
            ]

            outstanding_mandatory.sort(
                key=lambda bill: (
                    bill["due_date"],
                    bill["bill_id"]
                )
            )

            next_major = (
                outstanding_mandatory[0]
                if outstanding_mandatory
                else None
            )

            if next_major:
                next_name = next_major["name"]
                next_amount = next_major["amount"]
                next_due_date = next_major["due_date"]

                next_days = (
                    date.fromisoformat(next_due_date) - today
                ).days

            else:
                next_name = "None"
                next_amount = 0.0
                next_due_date = ""
                next_days = 0

            # --------------------------------------------------
            # 5. Calculate shortfall risk
            # --------------------------------------------------

            checking_available = float(
                state.checking.available_balance
            )

            purchase_amount = float(
                state.purchase_request.amount
            )

            if (
                not math.isfinite(checking_available)
                or not math.isfinite(purchase_amount)
            ):
                raise ValueError(
                    "Checking balance and purchase amount must be finite."
                )

            post_purchase_cash = (
                checking_available - purchase_amount
            )

            total_near_term_obligations = (
                total_overdue + total_7d
            )

            immediate_shortfall_risk = (
                post_purchase_cash < total_near_term_obligations
            )

            # --------------------------------------------------
            # 6. Update shared Pydantic state
            # --------------------------------------------------

            state.bill_analysis = BillAnalysisState(
                total_upcoming_bills_7d=round(total_7d, 2),
                total_upcoming_bills_30d=round(total_30d, 2),
                total_overdue_bills=round(total_overdue, 2),
                overdue_bill_count=len(mandatory_overdue),
                days_to_next_major_bill=next_days,
                next_major_bill_name=next_name,
                next_major_bill_amount=round(next_amount, 2),
                next_major_bill_due_date=next_due_date,
                immediate_shortfall_risk=immediate_shortfall_risk,
                bills_detail=enriched_bills
            )

            # --------------------------------------------------
            # 7. A2A message to Cash Flow Forecaster
            # --------------------------------------------------

            self.send_a2a_message(
                recipient_id="crewai_cash_flow",
                recipient_framework="CrewAI",
                recipient_role="Cash Flow Forecaster",
                topic="bills_summary",
                content={
                    "total_overdue": round(total_overdue, 2),
                    "overdue_count": len(mandatory_overdue),
                    "total_7d": round(total_7d, 2),
                    "total_30d": round(total_30d, 2),
                    "next_major_bill": next_name,
                    "next_amount": round(next_amount, 2),
                    "next_due_date": next_due_date,
                    "days_until_due": next_days,
                    "shortfall_risk": immediate_shortfall_risk
                },
                trace_id=state.trace_id,
                state_delta={
                    "bill_total_overdue": round(total_overdue, 2),
                    "bill_total_7d": round(total_7d, 2),
                    "bill_total_30d": round(total_30d, 2)
                }
            )

            # --------------------------------------------------
            # 8. Logging, callbacks and observability
            # --------------------------------------------------

            duration_ms = (
                time.time() - t0
            ) * 1000.0

            summary = (
                f"Overdue Mandatory Bills: ${total_overdue:,.2f} "
                f"({len(mandatory_overdue)} bills) | "
                f"Next 7 Days: ${total_7d:,.2f} | "
                f"Next 30 Days: ${total_30d:,.2f} | "
                f"Next Bill: {next_name} (${next_amount:,.2f}) "
                f"in {next_days} days | "
                f"Shortfall Risk: {immediate_shortfall_risk}"
            )

            self.callbacks.on_state_update(
                self.name,
                "CrewAI",
                "state.bill_analysis",
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
                    "bill_analysis": state.bill_analysis.model_dump()
                },
                duration_ms
            )

            state.add_trace(
                self.name,
                "CrewAI",
                "Recurring Bills Evaluation",
                "SUCCESS",
                "Analyze overdue and upcoming mandatory commitments",
                summary,
                duration_ms
            )

            logger.info(summary)

            return state

        except Exception as exc:

            duration_ms = (
                time.time() - t0
            ) * 1000.0

            logger.exception(
                "Bill Analysis Agent failed: %s",
                exc
            )

            try:
                self.callbacks.on_agent_finish(
                    self.name,
                    "CrewAI",
                    f"ERROR: {exc}",
                    duration_ms
                )
            except Exception:
                logger.exception(
                    "Failed to report Bill Analysis Agent error."
                )

            try:
                self.observability.end_span(
                    state.trace_id,
                    span,
                    {"error": str(exc)},
                    duration_ms
                )
            except Exception:
                logger.exception(
                    "Failed to close Bill Analysis observability span."
                )

            state.add_trace(
                self.name,
                "CrewAI",
                "Recurring Bills Evaluation",
                "ERROR",
                "Analyze recurring obligations",
                str(exc),
                duration_ms
            )

            raise


"""
Agent 10: Goal Progress Agent (CrewAI Framework).

Tracks savings goals, emergency fund coverage, reserve-floor protection,
and estimated goal delays using each goal's actual contribution target.
"""

import json
import logging
import math
import os
import time
from typing import Any, Dict, List, Optional

from agents.crewai_framework.crew_bridge import CrewAIDomainService
from core.state import FinGuardState, GoalProgressState

logger = logging.getLogger("FinGuard_GoalProgress")

DATA_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    ),
    "data",
)

GOALS_FILE = os.path.join(DATA_DIR, "savings_goals.json")


class GoalProgressAgent(CrewAIDomainService):
    def __init__(self):
        super().__init__(
            agent_id="crewai_goal_progress",
            name="Goal Progress Agent",
            role="Long-Term Wealth & Emergency Target Guardian",
            goal=(
                "Protect emergency savings and estimate the impact "
                "of purchases on long-term financial goals."
            ),
            backstory=(
                "A savings-goal analyst that evaluates emergency "
                "reserves and estimates contribution-based goal delays."
            ),
        )

    @staticmethod
    def _valid_amount(value: Any, field_name: str) -> float:
        """Validate and normalize a non-negative financial amount."""
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{field_name} must be a valid number."
            )

        if not math.isfinite(amount) or amount < 0:
            raise ValueError(
                f"{field_name} must be finite and non-negative."
            )

        return amount

    def _load_goals(self) -> List[Dict[str, Any]]:
        """Load and validate savings-goal records."""
        if not os.path.exists(GOALS_FILE):
            raise FileNotFoundError(
                f"Savings goals file not found: {GOALS_FILE}"
            )

        with open(GOALS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise ValueError(
                "savings_goals.json must contain a JSON list."
            )

        validated_goals = []
        seen_ids = set()

        for index, goal in enumerate(data):
            if not isinstance(goal, dict):
                raise ValueError(
                    f"Goal at index {index} must be a JSON object."
                )

            goal_id = str(goal.get("goal_id", "")).strip()
            name = str(goal.get("name", "")).strip()

            if not goal_id or not name:
                raise ValueError(
                    f"Goal at index {index} is missing goal_id or name."
                )

            if goal_id in seen_ids:
                raise ValueError(
                    f"Duplicate goal_id found: {goal_id}"
                )

            seen_ids.add(goal_id)

            target = self._valid_amount(
                goal.get("target_amount"),
                f"{name}.target_amount",
            )
            current = self._valid_amount(
                goal.get("current_amount"),
                f"{name}.current_amount",
            )
            contribution = self._valid_amount(
                goal.get("monthly_contribution_target", 0),
                f"{name}.monthly_contribution_target",
            )
            minimum_reserve = self._valid_amount(
                goal.get("minimum_lock_reserve", 0),
                f"{name}.minimum_lock_reserve",
            )

            if minimum_reserve > target:
                raise ValueError(
                    f"{name}: minimum_lock_reserve exceeds target_amount."
                )

            if current > target:
                logger.warning(
                    "%s has current_amount greater than its target.",
                    name,
                )

            validated_goal = dict(goal)
            validated_goal.update({
                "goal_id": goal_id,
                "name": name,
                "target_amount": target,
                "current_amount": current,
                "monthly_contribution_target": contribution,
                "minimum_lock_reserve": minimum_reserve,
            })

            validated_goals.append(validated_goal)

        return validated_goals

    @staticmethod
    def _find_emergency_goal(
        goals: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Identify the emergency-fund goal."""
        for goal in goals:
            if "emergency" in goal["name"].lower():
                return goal

        for goal in goals:
            if goal["minimum_lock_reserve"] > 0:
                return goal

        return None

    @staticmethod
    def _estimate_goal_delay(
        purchase_amount: float,
        goals: List[Dict[str, Any]],
    ) -> int:
        """
        Estimate the contribution-equivalent delay for the purchase.

        This is an estimate of how long it would take to rebuild the
        purchase amount through planned contributions. It is not a
        prediction that contributions will actually be reduced.
        """
        delays = []

        for goal in goals:
            monthly_contribution = goal[
                "monthly_contribution_target"
            ]

            if monthly_contribution <= 0:
                continue

            delay_days = (
                purchase_amount / monthly_contribution
            ) * 30.0

            delays.append(delay_days)

        if not delays:
            return 0

        # Use the longest contribution-equivalent delay as a
        # conservative single summary for the existing state field.
        return max(0, math.ceil(max(delays)))

    def run(self, state: FinGuardState) -> FinGuardState:
        start_time = time.time()

        self.callbacks.on_agent_start(
            self.name,
            "CrewAI",
            "Evaluating savings goals and emergency reserve protection",
        )

        span = self.observability.start_span(
            state.trace_id,
            self.name,
            "CrewAI",
            "evaluate_goal_impact",
        )

        try:
            goals = self._load_goals()

            purchase_amount = self._valid_amount(
                state.purchase_request.amount,
                "purchase_amount",
            )

            emergency_goal = self._find_emergency_goal(goals)

            if emergency_goal is None:
                raise ValueError(
                    "No emergency-fund goal or locked reserve "
                    "was found in savings_goals.json."
                )

            # Prefer the live savings account balance. If it is not
            # populated, use the configured goal balance.
            live_savings = self._valid_amount(
                state.savings.current_balance,
                "savings.current_balance",
            )

            emergency_current = (
                live_savings
                if live_savings > 0
                else emergency_goal["current_amount"]
            )

            emergency_target = self._valid_amount(
                state.savings.target_emergency_reserve,
                "savings.target_emergency_reserve",
            )

            if emergency_target <= 0:
                emergency_target = emergency_goal["target_amount"]

            reserve_floor = emergency_goal["minimum_lock_reserve"]

            coverage_pct = (
                emergency_current / emergency_target * 100.0
                if emergency_target > 0
                else 0.0
            )

            checking_balance = self._valid_amount(
                state.checking.available_balance,
                "checking.available_balance",
            )

            # Determine the possible checking shortfall.
            # Do not assume a savings transfer has actually occurred.
            checking_shortfall = max(
                0.0,
                purchase_amount - checking_balance,
            )

            # Conservative risk indicator: if the shortfall had to be
            # funded from emergency savings, would it breach the lock?
            potential_savings_after_shortfall = (
                emergency_current - checking_shortfall
            )

            violates_floor = (
                checking_shortfall > 0
                and potential_savings_after_shortfall < reserve_floor
            )

            delay_days = self._estimate_goal_delay(
                purchase_amount,
                goals,
            )

            state.goal_progress = GoalProgressState(
                active_goals=goals,
                emergency_fund_target=emergency_target,
                emergency_fund_current=emergency_current,
                emergency_fund_coverage_pct=round(
                    coverage_pct,
                    1,
                ),
                violates_emergency_reserve_floor=violates_floor,
                estimated_goal_delay_days=delay_days,
            )

            # Send the goal impact summary to the affordability evaluator.
            self.send_a2a_message(
                recipient_id="crewai_affordability",
                recipient_framework="CrewAI",
                recipient_role="Affordability Evaluator",
                topic="goal_impact_summary",
                content={
                    "emergency_fund_current": emergency_current,
                    "emergency_fund_target": emergency_target,
                    "coverage_pct": round(coverage_pct, 1),
                    "minimum_locked_reserve": reserve_floor,
                    "checking_shortfall": round(
                        checking_shortfall,
                        2,
                    ),
                    "potential_savings_after_shortfall": round(
                        potential_savings_after_shortfall,
                        2,
                    ),
                    "violates_floor": violates_floor,
                    "estimated_goal_delay_days": delay_days,
                    "delay_is_estimate": True,
                },
                trace_id=state.trace_id,
                state_delta={
                    "violates_floor": violates_floor,
                    "estimated_goal_delay_days": delay_days,
                },
            )

            duration_ms = (time.time() - start_time) * 1000.0

            summary = (
                f"Emergency Fund: ${emergency_current:,.2f} / "
                f"${emergency_target:,.2f} "
                f"({coverage_pct:.1f}% coverage). "
                f"Locked Reserve: ${reserve_floor:,.2f}. "
                f"Potential Floor Breach: {violates_floor}. "
                f"Estimated Contribution-Equivalent Delay: "
                f"{delay_days} days."
            )

            self.callbacks.on_state_update(
                self.name,
                "CrewAI",
                "state.goal_progress",
                summary,
            )

            self.callbacks.on_agent_finish(
                self.name,
                "CrewAI",
                summary,
                duration_ms,
            )

            self.observability.end_span(
                state.trace_id,
                span,
                {
                    "goal_progress": state.goal_progress.model_dump(),
                },
                duration_ms,
            )

            state.add_trace(
                self.name,
                "CrewAI",
                "Savings Goal & Emergency Cushion Audit",
                "SUCCESS",
                "Evaluate savings goals and emergency reserve",
                summary,
                duration_ms,
            )

            return state

        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000.0

            logger.exception(
                "Goal Progress Agent failed: %s",
                exc,
            )

            self.callbacks.on_agent_finish(
                self.name,
                "CrewAI",
                f"FAILED: {exc}",
                duration_ms,
            )

            self.observability.end_span(
                state.trace_id,
                span,
                {"error": str(exc)},
                duration_ms,
            )

            state.add_trace(
                self.name,
                "CrewAI",
                "Savings Goal & Emergency Cushion Audit",
                "FAILED",
                "Evaluate savings goals and emergency reserve",
                str(exc),
                duration_ms,
            )

            raise

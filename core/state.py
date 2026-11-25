"""
FinGuard State Management & Pydantic Data Models.
Implements Requirement 1 (Context Sharing & State Updates) and Requirement 3 (Structured Output using Pydantic).
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# ==========================================
# 1. Purchase Request Schema
# ==========================================
class PurchaseRequest(BaseModel):
    item_name: str = Field(..., description="Description of the item or expense")
    amount: float = Field(..., gt=0, description="Purchase cost in USD")
    category: str = Field(default="Shopping & Discretionary", description="Expense category")
    urgency: Literal["low", "medium", "high", "critical"] = Field(default="low", description="Urgency of the purchase")
    notes: Optional[str] = Field(default="", description="Additional context from user")


# ==========================================
# 2. Account Watcher State Schemas (ADK Agents)
# ==========================================
class CheckingAccountState(BaseModel):
    account_id: str = "acc_chk_01"
    name: str = "Everyday Checking Account"
    current_balance: float = 0.0
    available_balance: float = 0.0
    overdraft_protection: bool = False
    recent_transactions: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "active"


class CreditCardState(BaseModel):
    account_id: str = "acc_cc_02"
    name: str = "Cash Rewards Platinum Card"
    current_balance: float = 0.0
    credit_limit: float = 3000.0
    available_credit: float = 0.0
    apr_percentage: float = 24.99
    minimum_payment: float = 65.00
    next_payment_due_date: str = "2026-11-05"
    utilization_rate_pct: float = 0.0


class SavingsAccountState(BaseModel):
    account_id: str = "acc_sav_03"
    name: str = "High Yield Emergency Savings"
    current_balance: float = 0.0
    available_balance: float = 0.0
    interest_rate_apy: float = 4.25
    target_emergency_reserve: float = 5000.00
    safe_buffer_available: float = 0.0


class InvestmentAccountState(BaseModel):
    account_id: str = "acc_inv_04"
    name: str = "Growth & Index Brokerage"
    total_portfolio_value: float = 0.0
    cash_reserve: float = 0.0
    holdings: List[Dict[str, Any]] = Field(default_factory=list)
    daily_unrealized_change_pct: float = 0.0
    volatility_alert: Optional[str] = None


# ==========================================
# 3. Financial Analysis State Schemas (CrewAI Agents)
# ==========================================

class BillAnalysisState(BaseModel):
    # Mandatory outstanding obligations
    total_upcoming_bills_7d: float = 0.0
    total_upcoming_bills_30d: float = 0.0

    # Overdue obligations remain outstanding until payment is confirmed
    total_overdue_bills: float = 0.0
    overdue_bill_count: int = 0

    # Next outstanding mandatory obligation
    days_to_next_major_bill: int = 0
    next_major_bill_name: str = ""
    next_major_bill_amount: float = 0.0
    next_major_bill_due_date: str = ""

    immediate_shortfall_risk: bool = False

    # Complete enriched bill records
    bills_detail: List[Dict[str, Any]] = Field(default_factory=list)


class BudgetAnalysisState(BaseModel):
    category: str = ""
    monthly_limit: float = 0.0
    spent_to_date: float = 0.0
    remaining_budget: float = 0.0
    exceeds_budget_if_purchased: bool = False
    projected_overage_amount: float = 0.0
    category_status: str = "NORMAL"


class CashFlowForecastState(BaseModel):
    current_liquid_checking: float = 0.0
    projected_balance_after_purchase: float = 0.0
    projected_balance_after_bills_and_purchase: float = 0.0
    projected_cash_runway_days: int = 0
    will_trigger_overdraft: bool = False
    net_7d_cash_flow: float = 0.0
    cash_flow_trajectory: str = "STABLE"


class GoalProgressState(BaseModel):
    active_goals: List[Dict[str, Any]] = Field(default_factory=list)
    emergency_fund_target: float = 5000.0
    emergency_fund_current: float = 2450.0
    emergency_fund_coverage_pct: float = 49.0
    violates_emergency_reserve_floor: bool = False
    estimated_goal_delay_days: int = 0


# ==========================================
# 4. Risk / Anomaly State Schema (ADK Agent)
# ==========================================
class RiskAssessmentState(BaseModel):
    risk_score: int = Field(default=0, ge=0, le=100, description="Risk Score from 0 (Safe) to 100 (Critical)")
    risk_level: Literal["SAFE", "MODERATE", "ELEVATED", "CRITICAL"] = "SAFE"
    anomaly_flags: List[str] = Field(default_factory=list)
    credit_utilization_danger: bool = False
    liquidity_crisis_danger: bool = False
    market_drawdown_exposure: bool = False
    risk_summary: str = ""


# ==========================================
# 5. Affordability Decision State (CrewAI Agent)
# ==========================================
class AffordabilityEvaluationState(BaseModel):
    verdict: Literal["CAN_AFFORD", "CANNOT_AFFORD", "CONDITIONAL_AFFORD", "CRITICAL_DEFICIT"] = "CAN_AFFORD"
    confidence_score: float = Field(default=0.95, ge=0.0, le=1.0)
    primary_reason: str = ""
    affordability_ratio: float = 0.0
    stress_test_passed: bool = True


# ==========================================
# 6. Final Structured Output (Pydantic Output Requirement 3)
# ==========================================
class FinancialMetricRow(BaseModel):
    metric: str
    current_value: str
    post_purchase_value: str
    status: str
    impact: str


class TimelineCashEvent(BaseModel):
    date: str
    event: str
    cash_in_out: float
    projected_balance: float
    status: str


class FinGuardVerdict(BaseModel):
    item_name: str
    amount: float
    category: str
    verdict: Literal["CAN_AFFORD", "CANNOT_AFFORD", "CONDITIONAL_AFFORD", "CRITICAL_DEFICIT"]
    verdict_badge_color: str
    confidence_score: float
    headline: str
    executive_summary: str
    metrics_table: List[FinancialMetricRow] = Field(default_factory=list)
    cash_flow_timeline: List[TimelineCashEvent] = Field(default_factory=list)
    critical_warnings: List[str] = Field(default_factory=list)
    actionable_alternatives: List[str] = Field(default_factory=list)
    risk_breakdown: Dict[str, Any] = Field(default_factory=dict)
    provenance_trace_id: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_markdown(self) -> str:
        """Render the structured Pydantic verdict into an executive Markdown report."""
        badge_emoji = {
            "CAN_AFFORD": "✅ **CAN AFFORD**",
            "CANNOT_AFFORD": "❌ **CANNOT AFFORD**",
            "CONDITIONAL_AFFORD": "⚠️ **CONDITIONAL / PROCEED WITH CAUTION**",
            "CRITICAL_DEFICIT": "🚨 **CRITICAL FINANCIAL DEFICIT**",
        }.get(self.verdict, self.verdict)

        md = []
        md.append(f"# FinGuard Purchase Decision Report")
        md.append(f"**Item**: {self.item_name} | **Amount**: ${self.amount:,.2f} | **Category**: {self.category}")
        md.append(f"**Verdict**: {badge_emoji} *(Confidence: {self.confidence_score * 100:.0f}%)*")
        md.append(f"\n### Executive Summary\n{self.executive_summary}\n")

        if self.critical_warnings:
            md.append("### ⚠️ Critical Alerts")
            for w in self.critical_warnings:
                md.append(f"- 🔴 {w}")
            md.append("")

        md.append("### 📊 Financial Metrics Breakdown")
        md.append("| Metric | Current | Post-Purchase | Status | Impact |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")
        for row in self.metrics_table:
            md.append(f"| {row.metric} | {row.current_value} | {row.post_purchase_value} | {row.status} | {row.impact} |")
        md.append("")

        if self.cash_flow_timeline:
            md.append("### 🗓️ Projected 14-Day Cash Flow Timeline")
            md.append("| Date | Event | Cash Flow | Projected Balance | Status |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for t in self.cash_flow_timeline:
                flow_str = f"+${t.cash_in_out:,.2f}" if t.cash_in_out >= 0 else f"-${abs(t.cash_in_out):,.2f}"
                md.append(f"| {t.date} | {t.event} | {flow_str} | ${t.projected_balance:,.2f} | {t.status} |")
            md.append("")

        if self.actionable_alternatives:
            md.append("### 💡 Recommended Next Steps & Alternatives")
            for alt in self.actionable_alternatives:
                md.append(f"1. {alt}")
            md.append("")

        md.append(f"*(Audit Trace ID: `{self.provenance_trace_id}` | Timestamp: `{self.generated_at}`)*")
        return "\n".join(md)


# ==========================================
# 7. Central Shared Context State (Requirement 1: Context Sharing)
# ==========================================
class AgentTraceRecord(BaseModel):
    agent_name: str
    framework: Literal["ADK", "CrewAI", "MCP_Tool", "Guardrail"]
    step: str
    status: Literal["SUCCESS", "WARNING", "ERROR", "BLOCKED"]
    input_summary: str
    output_summary: str
    execution_time_ms: float
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class FinGuardState(BaseModel):
    """
    Central shared state passed and enriched across the 11-agent pipeline.
    Agents update their respective domains atomically.
    """
    session_id: str = "session_default"
    trace_id: str = Field(default_factory=lambda: f"fg_trace_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    purchase_request: PurchaseRequest
    checking: CheckingAccountState = Field(default_factory=CheckingAccountState)
    credit_card: CreditCardState = Field(default_factory=CreditCardState)
    savings: SavingsAccountState = Field(default_factory=SavingsAccountState)
    investment: InvestmentAccountState = Field(default_factory=InvestmentAccountState)
    bill_analysis: BillAnalysisState = Field(default_factory=BillAnalysisState)
    budget_analysis: BudgetAnalysisState = Field(default_factory=BudgetAnalysisState)
    cash_flow: CashFlowForecastState = Field(default_factory=CashFlowForecastState)
    goal_progress: GoalProgressState = Field(default_factory=GoalProgressState)
    risk_assessment: RiskAssessmentState = Field(default_factory=RiskAssessmentState)
    affordability: AffordabilityEvaluationState = Field(default_factory=AffordabilityEvaluationState)
    final_verdict: Optional[FinGuardVerdict] = None
    agent_traces: List[AgentTraceRecord] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def add_trace(self, agent_name: str, framework: str, step: str, status: str, input_s: str, output_s: str, runtime_ms: float):
        self.agent_traces.append(AgentTraceRecord(
            agent_name=agent_name,
            framework=framework,
            step=step,
            status=status,
            input_summary=input_s,
            output_summary=output_s,
            execution_time_ms=runtime_ms
        ))

"""
FinGuard — Light Fintech Dashboard
Frontend-only redesign. Uses the existing FinGuard backend.
"""

import os
import sys
import json

import streamlit as st

st.set_page_config(
    page_title="FinGuard | Financial Intelligence",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.orchestrator import default_orchestrator
from core.protocol_a2a import default_a2a_bus
from core.observability import default_observability
from mcp_service.tools import tool_plaid_db_lookup, tool_market_data_parser


# ----------------------------- THEME -----------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');

    :root {
        --ink: #17233b;
        --muted: #718096;
        --line: #e7edf5;
        --surface: #ffffff;
        --canvas: #f5f7fb;
        --blue: #315efb;
        --blue-soft: #edf2ff;
        --green: #12805c;
        --green-soft: #e9f7f1;
        --red: #c43d4b;
        --red-soft: #fff0f1;
        --amber: #a86b12;
        --amber-soft: #fff7e8;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
        color: var(--ink);
    }
    .stApp { background: var(--canvas); }
    [data-testid="stHeader"] { background: rgba(245,247,251,.92); }
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] > div { padding-top: 1.2rem; }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1440px;
    }
    h1, h2, h3 {
        font-family: 'Manrope', sans-serif;
        color: var(--ink);
        letter-spacing: -.03em;
    }
    h1 { font-size: 2rem !important; font-weight: 800 !important; }
    h2 { font-size: 1.35rem !important; font-weight: 750 !important; }
    h3 { font-size: 1.03rem !important; font-weight: 700 !important; }
    p, label, .stCaption { color: var(--muted); }

    [data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 18px 20px;
        box-shadow: 0 4px 16px rgba(28,45,82,.035);
    }
    [data-testid="stMetricLabel"] {
        color: var(--muted);
        font-weight: 600;
    }
    [data-testid="stMetricValue"] {
        color: var(--ink);
        font-family: 'Manrope',sans-serif;
    }
    div[data-testid="stForm"],
    div[data-testid="stExpander"],
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 16px;
        background: var(--surface);
    }
    div[data-testid="stForm"] { padding: 22px; }
    div[data-testid="stExpander"] { background: #fff; }

    .brand {
        display:flex;
        align-items:center;
        gap:11px;
        padding: 5px 4px 22px;
    }
    .brand-mark {
        width:42px;
        height:42px;
        border-radius:13px;
        background:#315efb;
        color:#fff;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:21px;
        box-shadow:0 7px 16px rgba(49,94,251,.22);
    }
    .brand-name {
        font-family:'Manrope',sans-serif;
        font-size:20px;
        font-weight:800;
        color:#17233b;
    }
    .brand-sub {
        color:#8995a8;
        font-size:11px;
        letter-spacing:.08em;
        text-transform:uppercase;
    }
    .eyebrow {
        color:#718096;
        font-size:11px;
        font-weight:700;
        letter-spacing:.12em;
        text-transform:uppercase;
    }
    .page-title {
        font-family:'Manrope',sans-serif;
        font-size:30px;
        font-weight:800;
        color:#17233b;
        letter-spacing:-1.2px;
        margin:2px 0 3px;
    }
    .page-subtitle {
        color:#718096;
        font-size:14px;
        margin-bottom:24px;
    }
    .panel {
        background:#fff;
        border:1px solid var(--line);
        border-radius:17px;
        padding:20px 22px;
        box-shadow:0 4px 16px rgba(28,45,82,.035);
        margin-bottom:16px;
    }
    .panel-title {
        font-family:'Manrope',sans-serif;
        font-size:16px;
        font-weight:750;
        color:#17233b;
        margin-bottom:5px;
    }
    .panel-note {
        color:#8793a6;
        font-size:12px;
        margin-bottom:14px;
    }
    .verdict {
        border-radius:18px;
        padding:23px 25px;
        margin:12px 0 20px;
        color:#17233b;
        border:1px solid var(--line);
        background:#fff;
    }
    .verdict.good {
        background:var(--green-soft);
        border-color:#c8eadb;
    }
    .verdict.bad {
        background:var(--red-soft);
        border-color:#f5d0d4;
    }
    .verdict.warn {
        background:var(--amber-soft);
        border-color:#f2dfb8;
    }
    .verdict h2 {
        margin:0 0 6px;
        color:#17233b;
    }
    .verdict p {
        margin:0;
        color:#526176;
    }
    .pill {
        display:inline-block;
        border-radius:999px;
        padding:4px 9px;
        font-size:11px;
        font-weight:700;
        background:#edf2ff;
        color:#315efb;
    }
    .small-muted { color:#8793a6;font-size:12px; }
    .stButton > button, .stFormSubmitButton > button {
        border-radius:10px;
        border:0;
        background:#315efb;
        color:#fff;
        font-weight:700;
        padding:.62rem 1.1rem;
        min-height:42px;
    }
    .stButton > button:hover,
    .stFormSubmitButton > button:hover {
        background:#244bd8;
        color:#fff;
    }
    input, textarea, [data-baseweb="select"] > div {
        border-radius:10px !important;
    }
    hr { border-color:var(--line); }
    footer { visibility:hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------- HELPERS ---------------------------------------

def money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def render_table(rows, empty_message="No records are available."):
    """Render simple HTML tables without Pandas or native dataframe extensions."""
    from html import escape

    if rows is None:
        st.caption(empty_message)
        return

    if isinstance(rows, dict):
        rows = [rows]

    if not isinstance(rows, (list, tuple)):
        st.write(rows)
        return

    normalized = []
    for item in rows:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        elif hasattr(item, "dict") and callable(item.dict):
            item = item.dict()

        if isinstance(item, dict):
            normalized.append(item)
        else:
            normalized.append({"Value": item})

    if not normalized:
        st.caption(empty_message)
        return

    columns = []
    for row in normalized:
        for key in row.keys():
            if key not in columns:
                columns.append(key)

    header_html = "".join(
        f"<th>{escape(str(column))}</th>" for column in columns
    )
    body_rows = []
    for row in normalized:
        cells = []
        for column in columns:
            value = row.get(column, "—")
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            cells.append(f"<td>{escape(str(value))}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table_html = (
        '<div style="overflow-x:auto;width:100%;">'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
        "<style>"
        "table th{background:#f5f7fb;color:#526176;text-align:left;"
        "font-weight:700;padding:10px;border-bottom:1px solid #e7edf5;}"
        "table td{padding:10px;border-bottom:1px solid #edf1f6;"
        "color:#26344d;vertical-align:top;}"
        "table tr:last-child td{border-bottom:0;}"
        "</style>"
    )
    st.markdown(table_html, unsafe_allow_html=True)


def load_accounts():
    result = tool_plaid_db_lookup("all", False) or {}
    return result.get("accounts", {})


def load_market():
    return tool_market_data_parser("ALL", 5) or {}


def page_header(title, subtitle):
    st.markdown(
        '<div class="eyebrow">FINGUARD / FINANCIAL INTELLIGENCE</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="page-title">{title}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="page-subtitle">{subtitle}</div>',
        unsafe_allow_html=True,
    )


def panel_title(title, note=None):
    st.markdown(
        f'<div class="panel-title">{title}</div>',
        unsafe_allow_html=True,
    )
    if note:
        st.markdown(
            f'<div class="panel-note">{note}</div>',
            unsafe_allow_html=True,
        )


def render_verdict(verdict):
    raw = str(getattr(verdict, "verdict", "REVIEW_REQUIRED"))

    if raw == "CAN_AFFORD":
        css, label = "good", "Purchase appears affordable"
    elif raw in ("CANNOT_AFFORD", "CRITICAL_DEFICIT"):
        css, label = "bad", "Purchase is not financially safe"
    else:
        css, label = "warn", "Further review recommended"

    confidence = getattr(verdict, "confidence_score", None)
    confidence_text = (
        f"{float(confidence) * 100:.0f}% confidence"
        if confidence is not None
        else "Confidence unavailable"
    )

    headline = getattr(verdict, "headline", label)
    summary = getattr(verdict, "executive_summary", "")

    st.markdown(
        f"""
        <div class="verdict {css}">
            <div class="eyebrow">FINANCIAL DECISION · {raw}</div>
            <h2>{headline}</h2>
            <p>{summary}</p>
            <div style="margin-top:14px;">
                <span class="pill">{confidence_text}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_result(state, purchase_name):
    verdict = getattr(state, "final_verdict", None)

    if verdict is None:
        st.warning("The analysis completed, but no final verdict was returned.")
        st.json(state.model_dump() if hasattr(state, "model_dump") else str(state))
        return

    render_verdict(verdict)

    left, right, third = st.columns(3)

    with left:
        st.metric(
            "Purchase amount",
            money(getattr(state, "purchase_amount", None)),
        )

    with right:
        st.metric(
            "Purchase",
            purchase_name,
        )

    with third:
        st.metric(
            "Decision",
            str(getattr(verdict, "verdict", "REVIEW")),
        )

    explanation = getattr(verdict, "reasoning", None)
    if explanation:
        with st.expander("View decision reasoning"):
            st.write(explanation)

    recommendations = getattr(verdict, "recommendations", []) or []
    if recommendations:
        with st.expander("Recommendations", expanded=True):
            for item in recommendations:
                st.write(f"• {item}")

    risks = getattr(verdict, "risk_factors", []) or []
    if risks:
        with st.expander("Risk factors"):
            for item in risks:
                st.write(f"• {item}")

    with st.expander("View complete analysis state"):
        if hasattr(state, "model_dump"):
            st.json(state.model_dump())
        elif hasattr(state, "dict"):
            st.json(state.dict())
        else:
            st.write(state)
            
def render_verdict(verdict):
    raw = str(getattr(verdict, "verdict", "REVIEW_REQUIRED"))

    if raw == "CAN_AFFORD":
        css, label = "good", "Purchase appears affordable"
    elif raw in ("CANNOT_AFFORD", "CRITICAL_DEFICIT"):
        css, label = "bad", "Purchase is not financially safe"
    else:
        css, label = "warn", "Further review recommended"

    confidence = getattr(verdict, "confidence_score", None)
    confidence_text = (
        f"{float(confidence) * 100:.0f}% confidence"
        if confidence is not None
        else "Confidence unavailable"
    )

    headline = getattr(verdict, "headline", label)
    summary = getattr(verdict, "executive_summary", "")

    st.markdown(
        f"""
        <div class="verdict {css}">
            <div class="eyebrow">FINANCIAL DECISION · {raw}</div>
            <h2>{headline}</h2>
            <p>{summary}</p>
            <p style="margin-top:12px;font-size:12px;font-weight:700;">
                {confidence_text}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_result(state, item_name):
    verdict = state.final_verdict
    render_verdict(verdict)

    warnings = getattr(verdict, "critical_warnings", None)
    if warnings:
        st.warning("Important financial warnings")
        for warning in warnings:
            st.markdown(f"- {warning}")

    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            panel_title(
                "Financial metrics",
                "Values returned by the FinGuard decision engine",
            )
            rows = [
                metric.model_dump()
                for metric in getattr(verdict, "metrics_table", [])
            ]
            if rows:
                render_table(rows)
            else:
                st.caption("No financial metrics were returned.")

    with right:
        with st.container(border=True):
            panel_title("Recommended next steps")
            alternatives = (
                getattr(verdict, "actionable_alternatives", []) or []
            )
            if alternatives:
                for index, alternative in enumerate(alternatives, 1):
                    st.markdown(f"**{index}.** {alternative}")
            else:
                st.caption("No additional recommendations were returned.")

    timeline = getattr(verdict, "cash_flow_timeline", []) or []
    if timeline:
        with st.container(border=True):
            panel_title("14-day projected cash flow")
            render_table([point.model_dump() for point in timeline])

    st.download_button(
        "Download decision report",
        data=verdict.to_markdown(),
        file_name=(
            f"FinGuard_{item_name.strip().replace(' ', '_')}_report.md"
        ),
        mime="text/markdown",
    )


# ----------------------------- SIDEBAR ---------------------------------------

with st.sidebar:
    st.markdown(
        """
        <div class="brand">
            <div class="brand-mark">盾</div>
            <div>
                <div class="brand-name">FinGuard</div>
                <div class="brand-sub">Financial intelligence</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="eyebrow">WORKSPACE</div>',
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Navigation",
        [
            "Overview",
            "Purchase analysis",
            "Accounts & markets",
            "Agent activity",
            "Benchmarks & security",
        ],
        label_visibility="collapsed",
        key="nav_page",
    )

    st.divider()
    st.markdown(
        '<div class="eyebrow">SYSTEM</div>',
        unsafe_allow_html=True,
    )

    native_mode = (
        os.getenv("FINGUARD_NATIVE_FRAMEWORKS", "false").lower()
        == "true"
    )

    st.markdown(
        f'<span class="pill">{"NATIVE ADK + CREWAI" if native_mode else "OFFLINE MODE"}</span>',
        unsafe_allow_html=True,
    )
    st.caption("Financial decision support workspace")


# ----------------------------- OVERVIEW --------------------------------------

if page == "Overview":
    page_header(
        "Financial overview",
        "A clear view of your financial position and purchase decisions.",
    )

    col1, col2, col3 = st.columns(3)

    try:
        accounts = load_accounts()
        market = load_market()

        account_values = list(accounts.values())
        total_balance = 0.0
        total_debt = 0.0

        for account in account_values:
            balance = float(account.get("balance", 0) or 0)
            account_type = str(
                account.get("type", "")
            ).lower()

            if "credit" in account_type or "loan" in account_type:
                total_debt += abs(balance)
            else:
                total_balance += balance

        with col1:
            st.metric(
                "Total available balance",
                money(total_balance),
            )

        with col2:
            st.metric(
                "Tracked debt",
                money(total_debt),
            )

        with col3:
            st.metric(
                "Market stress",
                str(market.get("market_stress_flag", "Not reported")),
            )

        st.divider()

        left, right = st.columns([1.25, 1])

        with left:
            with st.container(border=True):
                panel_title(
                    "Connected financial accounts",
                    "Account information returned by the configured data tool",
                )

                if accounts:
                    account_rows = []
                    for key, account in accounts.items():
                        account_rows.append({
                            "Account": account.get(
                                "name",
                                key.replace("_", " ").title(),
                            ),
                            "Type": account.get("type", "—"),
                            "Balance": money(
                                account.get("balance", 0)
                            ),
                        })

                    render_table(account_rows)
                else:
                    st.info("No account records are available.")

        with right:
            with st.container(border=True):
                panel_title(
                    "Market snapshot",
                    "Current market signals from the configured parser",
                )

                holdings = market.get("holdings_summary", [])
                if holdings:
                    render_table(holdings)
                else:
                    st.caption("No holdings summary is available.")

                anomalies = market.get("anomalies_detected", [])
                if anomalies:
                    st.warning("Market anomalies detected")
                    render_table(anomalies)

        st.divider()
        panel_title("Latest purchase decision")

        last_state = st.session_state.get("last_state")
        last_purchase = st.session_state.get("last_purchase")

        if last_state is not None:
            st.write(f"Most recent analysis: **{last_purchase}**")
            render_verdict(last_state.final_verdict)
        else:
            st.info("No purchase has been analysed in this session yet.")

    except Exception as exc:
        st.error(f"Unable to load the financial overview: {exc}")


# ----------------------------- PURCHASE ANALYSIS -----------------------------

elif page == "Purchase analysis":
    page_header(
        "Purchase analysis",
        "Understand whether a purchase fits your current financial position.",
    )

    with st.container(border=True):
        panel_title(
            "Tell us about your purchase",
            "FinGuard will evaluate the request using the configured orchestration pipeline.",
        )

        with st.form("finguard_purchase_form", clear_on_submit=False):
            col1, col2 = st.columns(2)

            with col1:
                item_name = st.text_input(
                    "Item or purchase name",
                    placeholder="e.g. Laptop",
                )

                amount = st.number_input(
                    "Purchase amount (USD)",
                    min_value=1.0,
                    value=250.0,
                    step=10.0,
                )

                category = st.selectbox(
                    "Spending category",
                    [
                        "Shopping & Discretionary",
                        "Dining & Takeout",
                        "Groceries",
                        "Transportation & Gas",
                        "Utilities & Subscriptions",
                        "Health & Fitness",
                    ],
                )

            with col2:
                urgency = st.selectbox(
                    "Urgency",
                    ["low", "medium", "high", "critical"],
                )

                notes = st.text_area(
                    "Additional context",
                    placeholder=(
                        "Upcoming bills, timing, or other relevant context"
                    ),
                    height=120,
                )

            submitted = st.form_submit_button(
                "Run FinGuard analysis",
                use_container_width=True,
            )

    if submitted:
        if not item_name.strip():
            st.error("Enter a purchase name before running the analysis.")
        else:
            try:
                with st.spinner(
                    "FinGuard is evaluating your purchase..."
                ):
                    state = default_orchestrator.evaluate_purchase(
                        item_name=item_name.strip(),
                        amount=amount,
                        category=category,
                        urgency=urgency,
                        notes=notes.strip(),
                    )

                st.session_state["last_state"] = state
                st.session_state["last_purchase"] = item_name.strip()
                st.success("Analysis completed.")

            except Exception as exc:
                st.error(f"Purchase analysis failed: {exc}")

    previous = st.session_state.get("last_state")

    if previous is not None:
        st.divider()
        st.subheader("Decision report")
        render_result(
            previous,
            st.session_state.get("last_purchase", "purchase"),
        )

# ----------------------------- ACCOUNTS & MARKETS ----------------------------

elif page == "Accounts & markets":
    page_header(
        "Accounts & market data",
        "Inspect the financial data sources used by the FinGuard agents.",
    )

    try:
        accounts_result = tool_plaid_db_lookup("all", True) or {}
        accounts = accounts_result.get("accounts", {})
        market = load_market()

        left, right = st.columns(2)

        with left:
            with st.container(border=True):
                panel_title(
                    "Banking and credit accounts",
                    "Sandbox account records",
                )

                if accounts:
                    for key, account in accounts.items():
                        with st.expander(
                            account.get(
                                "name",
                                key.replace("_", " ").title(),
                            )
                        ):
                            st.json(account)
                else:
                    st.info("No account records are available.")

        with right:
            with st.container(border=True):
                panel_title(
                    "Market data",
                    "Stored market holdings and volatility signals",
                )

                st.metric(
                    "Market stress flag",
                    str(market.get("market_stress_flag", "Not reported")),
                )

                holdings = market.get("holdings_summary", [])
                if holdings:
                    render_table(holdings)
                else:
                    st.info("No holdings summary is available.")

                anomalies = market.get("anomalies_detected", [])
                if anomalies:
                    st.warning("Market anomalies detected")
                    render_table(anomalies)

        bills_path = os.path.join(
            PROJECT_ROOT,
            "data",
            "recurring_bills.json",
        )

        if os.path.exists(bills_path):
            with st.container(border=True):
                panel_title(
                    "Recurring bills",
                    "Configured recurring obligations",
                )

                with open(bills_path, "r", encoding="utf-8") as file:
                    bills = json.load(file)

                render_table(bills)

    except Exception as exc:
        st.error(f"Unable to load account or market data: {exc}")


# ----------------------------- AGENT ACTIVITY --------------------------------

elif page == "Agent activity":
    page_header(
        "Agent activity",
        "Review the latest execution traces and agent-to-agent messages.",
    )

    state = st.session_state.get("last_state")

    if state is not None:
        traces = getattr(state, "agent_traces", []) or []

        with st.container(border=True):
            panel_title(
                "Latest pipeline execution",
                f"{len(traces)} recorded agent trace entries",
            )

            if traces:
                trace_rows = []

                for trace in traces:
                    trace_rows.append({
                        "Agent": getattr(
                            trace,
                            "agent_name",
                            getattr(trace, "agent_id", "Agent"),
                        ),
                        "Status": getattr(trace, "status", "Recorded"),
                        "Input": str(
                            getattr(trace, "input_summary", "")
                        )[:100],
                        "Output": str(
                            getattr(trace, "output_summary", "")
                        )[:140],
                    })

                render_table(trace_rows)
            else:
                st.info(
                    "The latest state contains no agent trace entries."
                )
    else:
        st.info(
            "Run a purchase analysis to populate execution details."
        )

    with st.container(border=True):
        panel_title(
            "A2A message history",
            "Messages recorded by the configured in-process message bus",
        )

        messages = (
            getattr(default_a2a_bus, "message_history", []) or []
        )

        if messages:
            rows = []

            for message in messages:
                rows.append({
                    "Timestamp": str(
                        getattr(message, "timestamp", "")
                    ),
                    "Sender": str(
                        getattr(
                            getattr(message, "sender", None),
                            "agent_id",
                            "",
                        )
                    ),
                    "Recipient": str(
                        getattr(
                            getattr(message, "recipient", None),
                            "agent_id",
                            "",
                        )
                    ),
                    "Topic": str(
                        getattr(message, "topic", "")
                    ),
                    "Performative": str(
                        getattr(message, "performative", "")
                    ),
                })

            render_table(rows)
        else:
            st.caption("No A2A messages have been recorded.")

    with st.container(border=True):
        panel_title("Observability traces")

        try:
            traces = default_observability.list_traces()

            if traces:
                render_table(traces)
            else:
                st.caption("No observability traces are available.")

        except Exception as exc:
            st.caption(f"Trace data unavailable: {exc}")


# ----------------------------- BENCHMARKS & SECURITY -------------------------

elif page == "Benchmarks & security":
    page_header(
        "Benchmarks & security",
        "Review evaluation results and the guardrails configured in this project.",
    )

    benchmark_path = os.path.join(
        PROJECT_ROOT,
        "evaluation",
        "benchmark_results.json",
    )

    if os.path.exists(benchmark_path):
        try:
            with open(
                benchmark_path,
                "r",
                encoding="utf-8",
            ) as file:
                benchmark = json.load(file)

            a, b, c, d = st.columns(4)

            accuracy = benchmark.get("accuracy_percentage")
            latency = benchmark.get("average_pipeline_latency_ms")
            scenarios = benchmark.get("total_scenarios_evaluated")
            cost = benchmark.get("average_cost_per_evaluation_usd")

            a.metric(
                "Decision accuracy",
                f"{accuracy}%" if accuracy is not None else "—",
            )

            b.metric(
                "Average latency",
                f"{latency} ms" if latency is not None else "—",
            )

            c.metric(
                "Scenarios evaluated",
                scenarios if scenarios is not None else "—",
            )

            d.metric(
                "Average cost",
                (
                    f"${cost:.6f}"
                    if isinstance(cost, (int, float))
                    else "—"
                ),
            )

            details = benchmark.get("scenario_details", [])

            if details:
                with st.container(border=True):
                    panel_title("Scenario results")
                    render_table(details)

        except Exception as exc:
            st.error(
                f"Unable to read benchmark results: {exc}"
            )

    else:
        st.info("No benchmark_results.json file was found.")

    with st.container(border=True):
        panel_title("Security and validation")

        st.markdown(
            """
            - **Input validation:** purchase inputs are passed through the project's guardrail layer.
            - **Financial invariants:** affordability calculations remain in the domain-service layer.
            - **Tool data:** account and market information is obtained through the configured data tools.
            - **Decision review:** warnings and recommended actions are displayed with the final verdict.
            """
        )

        st.caption(
            "This page describes the UI-visible controls; verify each "
            "security capability against its implementation before "
            "claiming it in a project demonstration."
        )


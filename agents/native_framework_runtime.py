
"""Native Google ADK and CrewAI execution for FinGuard.

Groups deterministic domain services into five native framework executions.
All financial calculations remain in the existing domain-service classes.
"""

import asyncio
import json
import os
import re
from typing import Any, Sequence

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=False)

MODEL = os.getenv("FINGUARD_MODEL", "gemini-3.8-flash")
AGENT_TIMEOUT = 90


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")[:40]


def _get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key or key == "your_gemini_api_key_here":
        raise RuntimeError(
            "A valid GEMINI_API_KEY is required for native framework execution."
        )

    # Keep ADK and CrewAI on the same configured key.
    os.environ["GOOGLE_API_KEY"] = key
    return key


def _run_services(services: Sequence[Any], state: Any) -> list:
    """Run existing audited domain services in their original order."""
    summaries = []

    for service in services:
        state = service.run(state)

        summary = (
            state.agent_traces[-1].output_summary
            if state.agent_traces
            else service.name
        )

        summaries.append({
            "agent": service.name,
            "status": "completed",
            "summary": str(summary)
        })

    return summaries


def run_native_adk_batch(services: Sequence[Any], state: Any) -> Any:
    """Run a group of domain services through one native ADK Agent + Runner."""

    if not services:
        return state

    api_key = _get_api_key()

    from google.adk.agents import Agent
    from google.adk.runners import InMemoryRunner
    from google.adk.tools import FunctionTool
    from google.genai import types

    execution = {"completed": False, "results": []}

    def execute_financial_operations() -> dict:
        """Execute all audited operations in this ADK phase exactly once."""

        if execution["completed"]:
            return {
                "status": "already_completed",
                "results": execution["results"]
            }

        results = _run_services(services, state)
        execution["results"] = results
        execution["completed"] = True

        return {
            "status": "completed",
            "agents_executed": len(results),
            "results": results
        }

    names = ", ".join(service.name for service in services)

    agent = Agent(
        name="finguard_adk_" + _slug(names),
        model=MODEL,
        description="FinGuard native ADK financial specialist group.",
        instruction=(
            f"You coordinate these FinGuard specialists: {names}. "
            "Call execute_financial_operations exactly once. "
            "Do not invent financial data, balances, or calculations. "
            "The tool result is authoritative."
        ),
        tools=[FunctionTool(func=execute_financial_operations)]
    )

    app_name = "finguard_adk_" + _slug(names)
    runner = InMemoryRunner(agent=agent, app_name=app_name)

    async def _run() -> None:
        user_id = "finguard_local_user"

        session = await runner.session_service.create_session(
            app_name=app_name,
            user_id=user_id
        )

        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        f"Evaluate purchase {state.purchase_request.item_name}, "
                        f"amount {state.purchase_request.amount}, "
                        f"category {state.purchase_request.category}. "
                        "Execute the required financial operations."
                    )
                )
            ]
        )

        async def consume_events():
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session.id,
                new_message=message
            ):
                if execution["completed"]:
                    break

        await asyncio.wait_for(
            consume_events(),
            timeout=AGENT_TIMEOUT
        )

    asyncio.run(_run())

    if not execution["completed"]:
        raise RuntimeError(
            f"ADK phase did not execute its tool. Specialists: {names}"
        )

    return state


def run_native_crewai_batch(services: Sequence[Any], state: Any) -> Any:
    """Run a group of domain services through one native CrewAI Agent."""

    if not services:
        return state

    api_key = _get_api_key()

    from crewai import Agent, Crew, Process, Task, LLM
    from crewai.tools import tool

    execution = {"completed": False, "results": []}

    @tool("execute_financial_operations")
    def execute_financial_operations() -> str:
        """Execute all audited FinGuard financial operations in this phase."""

        if execution["completed"]:
            return json.dumps({
                "status": "already_completed",
                "results": execution["results"]
            })

        results = _run_services(services, state)
        execution["results"] = results
        execution["completed"] = True

        return json.dumps({
            "status": "completed",
            "agents_executed": len(results),
            "results": results
        })

    names = ", ".join(service.name for service in services)

    llm = LLM(
        model=f"gemini/{MODEL}",
        api_key=api_key,
        temperature=0,
        timeout=AGENT_TIMEOUT
    )

    agent = Agent(
        role="FinGuard financial analysis coordinator",
        goal=f"Execute the financial operations for: {names}",
        backstory=(
            "You coordinate FinGuard financial specialists. "
            "All financial calculations are performed by audited tools."
        ),
        llm=llm,
        tools=[execute_financial_operations],
        allow_delegation=False,
        verbose=False,
        max_iter=2,
        max_execution_time=AGENT_TIMEOUT
    )

    task = Task(
        description=(
            f"Process the purchase {state.purchase_request.item_name}, "
            f"amount {state.purchase_request.amount}, "
            f"category {state.purchase_request.category}. "
            "Call execute_financial_operations exactly once. "
            "Do not invent financial figures or override tool results."
        ),
        expected_output=(
            "The authoritative result returned by "
            "execute_financial_operations."
        ),
        agent=agent
    )

    Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False
    ).kickoff()

    if not execution["completed"]:
        raise RuntimeError(
            f"CrewAI phase did not execute its tool. Specialists: {names}"
        )

    return state


# Backwards-compatible single-service functions.
def run_native_adk(domain_service: Any, state: Any) -> Any:
    return run_native_adk_batch([domain_service], state)


def run_native_crewai(domain_service: Any, state: Any) -> Any:
    return run_native_crewai_batch([domain_service], state)

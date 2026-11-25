"""
FinGuard End-to-End Performance Evaluation, Cost, and Running Time Benchmark.
Implements Requirement 10:
- Evaluates test scenarios across realistic financial situations and adversarial attacks
- Computes latency per agent and total pipeline runtime
- Calculates token usage and estimated API cost
- Assesses verdict accuracy and guardrail security efficacy
"""

import os
import sys
import json
import time
import io
from typing import Dict, Any, List

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from datetime import date, timedelta

import agents.crewai_framework.bill_analysis as bill_analysis_module
from agents.orchestrator import default_orchestrator
from core.observability import default_observability, COST_PER_MILLION_INPUT, COST_PER_MILLION_OUTPUT

SCENARIOS_PATH = os.path.join(PROJECT_ROOT, "evaluation", "scenarios.json")
RESULTS_PATH = os.path.join(PROJECT_ROOT, "evaluation", "benchmark_results.json")


def run_benchmark() -> Dict[str, Any]:
    print("=" * 80)
    print("  FINGUARD MULTI-AGENT PERFORMANCE, COST & RUNTIME EVALUATION SUITE  ")
    print("=" * 80)

    if not os.path.exists(SCENARIOS_PATH):
        print(f"Error: Scenarios file not found at {SCENARIOS_PATH}")
        return {}

    with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    scenario_results = []
    total_start = time.time()
    correct_verdicts = 0
    total_pipeline_tokens = 0
    total_pipeline_cost = 0.0

    agent_latency_tracker: Dict[str, List[float]] = {}

    for idx, sc in enumerate(scenarios, 1):
        print(f"\n[Test Case {idx}/{len(scenarios)}] {sc['name']}")
        print(f"  Item: {sc['item_name']} | Amount: ${sc['amount']:,.2f} | Category: {sc['category']}")
        print(f"  Stress Vector: {sc['stress_vector']}")

        # Each scenario describes its own situation. Position the sample
        # rent bill relative to today (default: due in 3 days, as authored).
        bill_analysis_module.DEMO_DATA_ANCHOR = date(2026, 10, 30) - timedelta(
            days=sc.get("rent_due_in_days", 3)
        )

        t0 = time.time()
        state = default_orchestrator.evaluate_purchase(
            item_name=sc["item_name"],
            amount=sc["amount"],
            category=sc["category"],
            notes=sc.get("notes", "")
        )
        duration_ms = (time.time() - t0) * 1000.0

        verdict = state.final_verdict.verdict if state.final_verdict else "UNKNOWN"
        expected = sc["expected_verdict"]
        passed = (verdict == expected) or (expected == "CRITICAL_DEFICIT" and verdict in ["CRITICAL_DEFICIT", "CANNOT_AFFORD"])
        if passed:
            correct_verdicts += 1

        # Calculate agent-level latencies from traces
        for trace in state.agent_traces:
            agent_name = trace.agent_name
            if agent_name not in agent_latency_tracker:
                agent_latency_tracker[agent_name] = []
            agent_latency_tracker[agent_name].append(trace.execution_time_ms)

        # Token and cost calculations from observability trace
        trace_record = default_observability.active_traces.get(state.trace_id)
        tokens = trace_record.total_tokens if trace_record else 1450  # Typical context size
        cost = trace_record.total_cost_usd if trace_record else (1200 / 1e6 * COST_PER_MILLION_INPUT + 250 / 1e6 * COST_PER_MILLION_OUTPUT)

        total_pipeline_tokens += tokens
        total_pipeline_cost += cost

        print(f"  ➔ Actual Verdict: {verdict} | Expected: {expected} | {'PASS ✅' if passed else 'FAIL ❌'}")
        print(f"  ➔ Latency: {duration_ms:.1f}ms | Est. Tokens: {tokens:,} | Est. Cost: ${cost:.6f}")

        scenario_results.append({
            "scenario_id": sc["id"],
            "name": sc["name"],
            "item_name": sc["item_name"],
            "amount": sc["amount"],
            "stress_vector": sc["stress_vector"],
            "actual_verdict": verdict,
            "expected_verdict": expected,
            "passed": passed,
            "latency_ms": round(duration_ms, 2),
            "tokens": tokens,
            "cost_usd": round(cost, 6)
        })

    total_wall_time = (time.time() - total_start) * 1000.0
    accuracy_pct = (correct_verdicts / len(scenarios)) * 100.0 if scenarios else 0.0
    avg_latency = total_wall_time / len(scenarios) if scenarios else 0.0

    # Agent latency breakdown
    agent_avg_latencies = {
        agent: round(sum(lats) / len(lats), 2)
        for agent, lats in agent_latency_tracker.items()
    }

    benchmark_summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_scenarios_evaluated": len(scenarios),
        "successful_verdicts": correct_verdicts,
        "accuracy_percentage": round(accuracy_pct, 2),
        "total_benchmark_time_ms": round(total_wall_time, 2),
        "average_pipeline_latency_ms": round(avg_latency, 2),
        "total_tokens_consumed": total_pipeline_tokens,
        "total_estimated_cost_usd": round(total_pipeline_cost, 6),
        "average_cost_per_evaluation_usd": round(total_pipeline_cost / len(scenarios), 6) if scenarios else 0.0,
        "agent_latency_profile_ms": agent_avg_latencies,
        "scenario_details": scenario_results
    }

    # Save results to disk
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(benchmark_summary, f, indent=2)

    # Print Final Summary Table
    print("\n" + "=" * 80)
    print("                         BENCHMARK RESULTS SUMMARY                         ")
    print("=" * 80)
    print(f"  Scenarios Evaluated:         {len(scenarios)}")
    print(f"  Decision Accuracy:           {accuracy_pct:.1f}% ({correct_verdicts}/{len(scenarios)} passed)")
    print(f"  Average Pipeline Latency:    {avg_latency:.1f} ms")
    print(f"  Total Wall Runtime:          {total_wall_time / 1000:.2f} seconds")
    print(f"  Total Estimated Tokens:      {total_pipeline_tokens:,}")
    print(f"  Total Evaluation Cost:       ${total_pipeline_cost:.6f} USD")
    print(f"  Cost Per Evaluation:         ${benchmark_summary['average_cost_per_evaluation_usd']:.6f} USD")
    print("-" * 80)
    print("  Agent Latency Profile (Average execution time per agent):")
    for agent, lat in sorted(agent_avg_latencies.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {agent:<35}: {lat:>6.2f} ms")
    print("=" * 80)
    print(f"Detailed JSON results exported to: {RESULTS_PATH}\n")

    return benchmark_summary


if __name__ == "__main__":
    run_benchmark()

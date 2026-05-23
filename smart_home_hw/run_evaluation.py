"""
Entry point for evaluating RequestSolver strategies on the homework test set.

Usage:
    python run_evaluation.py

This script:
    1. Loads requests and preferences from ../requests.json and ../preferences.json
    2. Instantiates EnvironmentManagerAgent
    3. Runs FullContextSolver, SequentialSolver, and SemanticSolver
    4. Prints aggregated metrics for each strategy
    5. Saves metrics to ../results/evaluation_metrics.json
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Type

from models import Request, ActionOutput, Preference, TimeInterval
from environment_manager import EnvironmentManagerAgent
from request_solver import FullContextSolver, SequentialSolver, SemanticSolver
from evaluation import evaluate_single, EvaluationMetrics
from llm_client import get_llm_client


SIMULATOR_URL = "http://localhost:8080"
HOMEWORK_DIR = Path(__file__).parent.parent
VERBOSE = os.getenv("VERBOSE_AGENTS", "").lower() in ("1", "true", "yes")
AGENT_STARTUP_DELAY = 0.5


def load_requests(filepath: Path) -> list[Request]:
    """Load requests from JSON file."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    requests = []
    for entry in data:
        output = [ActionOutput(**out) for out in entry.get("output", [])]
        req = Request(
            id=entry["id"],
            issued_at=entry.get("issued_at", "12:00"),
            input=entry["input"],
            output=output,
        )
        requests.append(req)

    return requests


def load_preferences(filepath: Path) -> list[Preference]:
    """Load preferences from JSON file."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    preferences = []
    for entry in data:
        pref = Preference(
            device_type=entry["device_type"],
            room=entry["room"],
            dislike_interval=TimeInterval(**entry["dislike_interval"]),
            reason=entry.get("reason", ""),
        )
        preferences.append(pref)

    return preferences


def accumulate_metrics(metrics: EvaluationMetrics, result, duration: float) -> None:
    """Accumulate one TestResult into EvaluationMetrics."""
    metrics.total_tests += 1

    if result.success == "True":
        metrics.successful_tests += 1
    elif result.success == "Quantifiable":
        metrics.quantifiable_tests += 1
    else:
        metrics.failed_tests += 1

    metrics.total_expected_actions += len(result.expected_actions)
    metrics.total_matched_actions += len(result.matched_actions)
    metrics.total_missing_actions += len(result.missing_actions)
    metrics.total_extra_actions += len(result.extra_actions)

    metrics.total_properties_checked += result.properties_checked
    metrics.total_properties_matched += result.properties_matched

    metrics.total_expected_impossible += result.expected_impossible
    metrics.total_detected_impossible += len(result.detected_impossible)

    metrics.total_duration += duration

    if result.failure_type:
        if result.failure_type in metrics.failures_by_type:
            metrics.failures_by_type[result.failure_type] += 1
        else:
            metrics.failures_by_type["other"] += 1


def run_strategy(
    strategy_name: str,
    solver_cls: Type,
    requests: list[Request],
    env_manager: EnvironmentManagerAgent,
    llm_client,
) -> dict:
    """Run one solver strategy and return metrics/results."""
    print("\n" + "=" * 70)
    print(f"Running strategy: {strategy_name}")
    print("=" * 70)

    solver = solver_cls(env_manager, llm_client, verbose=VERBOSE)
    metrics = EvaluationMetrics()
    results = []

    for req_idx, request in enumerate(requests):
        start = time.time()

        try:
            predicted = solver.solve(request)
            duration = time.time() - start

        except Exception as e:
            predicted = []
            duration = time.time() - start
            print(f"\n[{req_idx + 1}/{len(requests)}] {request.id}")
            print(f"  ERROR during solve: {type(e).__name__}: {e}")

        result = evaluate_single(request, predicted, SIMULATOR_URL, timeout=30)
        result.duration_seconds = duration
        results.append(result)

        accumulate_metrics(metrics, result, duration)

        print(
            f"[{req_idx + 1:02d}/{len(requests)}] "
            f"{request.id:30} — {result.success}"
        )

    return {
        "strategy": strategy_name,
        "metrics": metrics.to_dict(),
        "results": [
            {
                "test_id": r.test_id,
                "success": r.success,
                "failure_type": r.failure_type,
                "error": r.error,
                "matched_actions": r.matched_actions,
                "missing_actions": r.missing_actions,
                "extra_actions": r.extra_actions,
                "properties_checked": r.properties_checked,
                "properties_matched": r.properties_matched,
                "expected_impossible": r.expected_impossible,
                "detected_impossible": r.detected_impossible,
                "duration_seconds": r.duration_seconds,
            }
            for r in results
        ],
    }


def print_comparison_table(strategy_outputs: list[dict]) -> None:
    """Print a compact metrics table for the report."""
    print("\n" + "=" * 90)
    print("Strategy Comparison")
    print("=" * 90)

    headers = [
        "Strategy",
        "Success",
        "Success+Quant",
        "Action F1",
        "Property Acc.",
        "Impossible Det.",
        "Avg Time",
    ]

    rows = []
    for output in strategy_outputs:
        m = output["metrics"]
        rows.append(
            [
                output["strategy"],
                f"{m['success_rate']:.1%}",
                f"{m['success_or_quantifiable_rate']:.1%}",
                f"{m['action_f1']:.1%}",
                f"{m['property_accuracy']:.1%}",
                f"{m['impossible_detection_rate']:.1%}",
                f"{m['avg_duration']:.2f}s",
            ]
        )

    widths = [
        max(len(str(row[i])) for row in [headers] + rows)
        for i in range(len(headers))
    ]

    print(" | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(str(row[i]).ljust(widths[i]) for i in range(len(row))))


def save_metrics(strategy_outputs: list[dict]) -> Path:
    """Save metrics/results to ../results/evaluation_metrics.json."""
    results_dir = HOMEWORK_DIR / "results"
    results_dir.mkdir(exist_ok=True)

    output_file = results_dir / "evaluation_metrics.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(strategy_outputs, f, indent=2)

    return output_file


def main() -> int:
    """Run evaluation for all strategies."""
    print("=" * 70)
    print("SmartHome Homework Evaluation")
    print("=" * 70)

    requests_file = HOMEWORK_DIR / "requests.json"
    prefs_file = HOMEWORK_DIR / "preferences.json"

    if not requests_file.exists() or not prefs_file.exists():
        print("Error: Test files not found")
        print(f"  Expected: {requests_file}")
        print(f"  Expected: {prefs_file}")
        return 1

     requests = load_requests(requests_file)
preferences = load_preferences(prefs_file)

limit = int(os.getenv("EVAL_LIMIT", "0"))
if limit > 0:
    requests = requests[:limit]
    print(f"Debug limit enabled: evaluating first {limit} requests")

    print(f"\nLoaded {len(requests)} requests")
    print(f"Loaded {len(preferences)} preferences")
    print(f"Simulator URL: {SIMULATOR_URL}")

    try:
        llm_client = get_llm_client()
        print("✓ LLM client initialized")
    except Exception as e:
        llm_client = None
        print(f"⚠ LLM client unavailable: {e}")
        print("  Solvers will use deterministic fallback parsing where possible.")

    env_manager = EnvironmentManagerAgent(SIMULATOR_URL, preferences, verbose=VERBOSE)
    env_manager.start()
    print("✓ EnvironmentManager agent started")

    time.sleep(AGENT_STARTUP_DELAY)

    strategies = [
        ("Full Context", FullContextSolver),
        ("Sequential Exploration", SequentialSolver),
        ("Semantic Classification", SemanticSolver),
    ]

    strategy_outputs = []

    try:
        for strategy_name, solver_cls in strategies:
            output = run_strategy(
                strategy_name=strategy_name,
                solver_cls=solver_cls,
                requests=requests,
                env_manager=env_manager,
                llm_client=llm_client,
            )
            strategy_outputs.append(output)

        print_comparison_table(strategy_outputs)

        output_file = save_metrics(strategy_outputs)
        print("\nSaved metrics to:")
        print(f"  {output_file}")

    finally:
        print("\n" + "=" * 70)
        print("Shutting down agents...")
        print("=" * 70)
        env_manager.stop()
        print("✓ EnvironmentManager agent stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
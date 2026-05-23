"""Evaluation metrics and test result tracking."""

from dataclasses import dataclass, field
from typing import Literal, Optional
import requests


@dataclass
class TestResult:
    """Result of running a single test case."""
    test_id: str
    success: Literal["True", "False", "Quantifiable"]

    # Planning metrics
    plan_generated: bool = False
    plan_format: str = ""
    actions_in_plan: list[str] = field(default_factory=list)
    params_in_plan: dict = field(default_factory=dict)  # action_url -> params

    # Execution metrics
    execution_success: bool = False
    execution_ticks: int = 0

    # Comparison metrics
    expected_actions: list[str] = field(default_factory=list)
    expected_params: dict = field(default_factory=dict)  # action_url -> params
    matched_actions: list[str] = field(default_factory=list)
    missing_actions: list[str] = field(default_factory=list)
    extra_actions: list[str] = field(default_factory=list)
    params_correct: bool = False

    # Property verification
    properties_checked: int = 0
    properties_matched: int = 0
    property_results: list[dict] = field(default_factory=list)

    # Impossible sub-goal detection (error_input cases)
    expected_impossible: int = 0  # Count of error_input in ground truth
    detected_impossible: list[str] = field(default_factory=list)  # Reported as impossible
    is_error_input_only: bool = False  # All expected outputs are error_input
    handled_correctly: bool = False  # For error cases: didn't attempt; for success: all matched

    # Timing
    duration_seconds: float = 0.0

    # Failure tracking
    failure_type: Optional[str] = None
    error: Optional[str] = None
    raw_result: Optional[dict] = None


@dataclass
class EvaluationMetrics:
    """Aggregated evaluation metrics across all tests."""
    total_tests: int = 0
    successful_tests: int = 0
    quantifiable_tests: int = 0  # Partially successful
    failed_tests: int = 0

    # Planning
    plans_generated: int = 0

    # Action matching
    total_expected_actions: int = 0
    total_matched_actions: int = 0
    total_missing_actions: int = 0
    total_extra_actions: int = 0

    # Property verification
    total_properties_checked: int = 0
    total_properties_matched: int = 0

    # Impossible sub-goal detection
    total_expected_impossible: int = 0  # Total error_input sub-goals in ground truth
    total_detected_impossible: int = 0  # Total sub-goals reported as impossible

    # Failure type tracking
    failures_by_type: dict = field(default_factory=lambda: {
        "parse_error": 0,
        "compilation_error": 0,
        "execution_error": 0,
        "action_mismatch": 0,
        "property_mismatch": 0,
        "error_input_not_detected": 0,
        "other": 0,
    })

    # Timing
    total_duration: float = 0.0

    @property
    def success_rate(self) -> float:
        """Rate of fully successful tests."""
        return self.successful_tests / self.total_tests if self.total_tests > 0 else 0.0

    @property
    def quantifiable_rate(self) -> float:
        """Rate of quantifiable (partially successful) tests."""
        return self.quantifiable_tests / self.total_tests if self.total_tests > 0 else 0.0

    @property
    def success_or_quantifiable_rate(self) -> float:
        """Rate of successful or quantifiable tests."""
        return (self.successful_tests + self.quantifiable_tests) / self.total_tests if self.total_tests > 0 else 0.0

    @property
    def action_precision(self) -> float:
        """Precision: matched / (matched + extra)."""
        total = self.total_matched_actions + self.total_extra_actions
        return self.total_matched_actions / total if total > 0 else 0.0

    @property
    def action_recall(self) -> float:
        """Recall: matched / expected."""
        return self.total_matched_actions / self.total_expected_actions if self.total_expected_actions > 0 else 0.0

    @property
    def action_f1(self) -> float:
        """F1 score for action matching."""
        p, r = self.action_precision, self.action_recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def property_accuracy(self) -> float:
        """Property verification accuracy."""
        return self.total_properties_matched / self.total_properties_checked if self.total_properties_checked > 0 else 0.0

    @property
    def impossible_detection_rate(self) -> float:
        """Rate of detecting impossible sub-goals."""
        if self.total_expected_impossible == 0:
            return 1.0  # No impossible sub-goals, "perfect" detection
        return min(1.0, self.total_detected_impossible / self.total_expected_impossible)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_tests": self.total_tests,
            "successful_tests": self.successful_tests,
            "quantifiable_tests": self.quantifiable_tests,
            "failed_tests": self.failed_tests,
            "success_rate": self.success_rate,
            "quantifiable_rate": self.quantifiable_rate,
            "success_or_quantifiable_rate": self.success_or_quantifiable_rate,
            "plans_generated": self.plans_generated,
            "action_precision": self.action_precision,
            "action_recall": self.action_recall,
            "action_f1": self.action_f1,
            "total_expected_actions": self.total_expected_actions,
            "total_matched_actions": self.total_matched_actions,
            "total_missing_actions": self.total_missing_actions,
            "total_extra_actions": self.total_extra_actions,
            "property_accuracy": self.property_accuracy,
            "total_properties_checked": self.total_properties_checked,
            "total_properties_matched": self.total_properties_matched,
            "total_expected_impossible": self.total_expected_impossible,
            "total_detected_impossible": self.total_detected_impossible,
            "impossible_detection_rate": self.impossible_detection_rate,
            "failures_by_type": self.failures_by_type,
            "total_duration": self.total_duration,
            "avg_duration": self.total_duration / self.total_tests if self.total_tests > 0 else 0,
        }


def execute_action(
    affordance_uri: str,
    params: dict,
    simulator_url: str = "http://localhost:8080",
    timeout: int = 30,
) -> dict:
    """
    Execute a single action at the simulator.

    Args:
        affordance_uri: The action URI (e.g., http://localhost:8080/workspaces/home1/master_bedroom/artifacts/masterBedroomLight/turn_on)
        params: Action parameters as a dict
        simulator_url: Base URL of the simulator
        timeout: HTTP timeout in seconds

    Returns:
        Response from simulator or error dict
    """
    try:
        response = requests.post(
            affordance_uri,
            json=params,
            timeout=timeout,
        )
        response.raise_for_status()
        return {"status": "success", "data": response.json()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def read_property(
    property_uri: str,
    simulator_url: str = "http://localhost:8080",
    timeout: int = 30,
) -> dict:
    """
    Read a single property value from the simulator.

    Args:
        property_uri: The property URI (e.g., http://localhost:8080/workspaces/home1/master_bedroom/artifacts/masterBedroomLight/properties/brightness)
        simulator_url: Base URL of the simulator
        timeout: HTTP timeout in seconds

    Returns:
        Dict with 'value' key if successful, or 'error' key if failed
    """
    try:
        response = requests.get(
            property_uri,
            timeout=timeout,
        )
        response.raise_for_status()
        json_result = response.json()
        # Ensure we always return a dict
        if isinstance(json_result, dict):
            return json_result
        else:
            return {"value": json_result}
    except Exception as e:
        return {"error": str(e)}


def reset_home(
    home_id: str,
    simulator_url: str = "http://localhost:8080",
    timeout: int = 30,
) -> bool:
    """
    Reset a home to its initial state.

    Args:
        home_id: Home ID (e.g., "home1" or "1")
        simulator_url: Base URL of the simulator
        timeout: HTTP timeout in seconds

    Returns:
        True if reset succeeded, False otherwise
    """
    try:
        # Extract the number from home_id (e.g., "home71" -> "71")
        if home_id.startswith("home"):
            home_num = home_id[4:]
        else:
            home_num = home_id

        response = requests.post(
            f"{simulator_url}/reset",
            json={"home": home_num},
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Warning: Failed to reset {home_id}: {e}")
        return False


def evaluate_single(
    request,
    predicted,
    simulator_url: str = "http://localhost:8080",
    timeout: int = 30,
) -> TestResult:
    """
    Evaluate a single request by executing predicted actions and comparing results.

    Args:
        request: Request object with id, issued_at, input, output (ground truth)
        predicted: List of predicted ActionOutput objects
        simulator_url: Base URL of the simulator
        timeout: HTTP timeout in seconds

    Returns:
        TestResult with execution and comparison metrics
    """
    result = TestResult(test_id=request.id, success="False")
    result.plan_generated = True
    home_id = request.id.split("_")[0]

    # Extract expected outputs (ground truth)
    expected_actions = []
    expected_params = {}
    expected_impossible = 0
    expected_tests = {}

    for out in request.output:
        # Handle both dict and ActionOutput
        if isinstance(out, dict):
            execution = out.get("execution")
            affordance = out.get("affordance")
            params = out.get("params", {})
            test = out.get("test")
        else:
            execution = out.execution
            affordance = out.affordance
            params = out.params
            test = out.test

        if execution == "error_input":
            expected_impossible += 1
        elif execution == "success" and affordance:
            expected_actions.append(affordance)
            expected_params[affordance] = params
            if test:
                expected_tests[affordance] = test

    result.expected_actions = expected_actions
    result.expected_params = expected_params
    result.expected_impossible = expected_impossible

    # Extract predicted outputs and execute them
    predicted_actions = []
    predicted_impossible = 0
    predicted_by_idx = {}

    for out_idx, out in enumerate(predicted):
        if isinstance(out, dict):
            action_out = out
        else:
            action_out = {
                "execution": out.execution,
                "affordance": out.affordance,
                "params": out.params,
            }

        if action_out.get("execution") == "error_input":
            predicted_impossible += 1
        elif action_out.get("execution") == "success" and action_out.get("affordance"):
            affordance = action_out["affordance"]
            predicted_actions.append(affordance)
            predicted_by_idx[affordance] = action_out

            # Execute the action
            params = action_out.get("params", {})
            exec_result = execute_action(affordance, params, simulator_url, timeout)

            if exec_result["status"] != "success":
                # Log the error but continue evaluation
                if not result.error:
                    result.error = f"Action execution failed: {exec_result.get('error')}"

    result.total_detected_impossible = predicted_impossible
    result.is_error_input_only = (len(expected_actions) == 0 and expected_impossible > 0)

    if result.is_error_input_only:
        # For error_input-only cases, success if predicted also detected error
        if predicted_impossible > 0:
            result.success = "True"
            result.handled_correctly = True
            result.execution_success = True
        else:
            result.success = "False"
            result.handled_correctly = False
            result.execution_success = False
    else:
        # Normal case: match actions and verify properties
        matched = []
        missing = []

        for action in expected_actions:
            if action in predicted_actions:
                matched.append(action)
            else:
                missing.append(action)

        extra = [a for a in predicted_actions if a not in expected_actions]

        result.matched_actions = matched
        result.missing_actions = missing
        result.extra_actions = extra
        result.execution_success = True

        # Verify properties for matched actions
        properties_matched = 0
        properties_checked = 0

        for affordance in matched:
            if affordance in expected_tests:
                properties_checked += 1
                test = expected_tests[affordance]
                prop_uri = test.get("property")
                expected_value = test.get("expected_value")

                # Read the actual property value
                prop_result = read_property(prop_uri, simulator_url, timeout)

                # Ensure prop_result is a dict
                if not isinstance(prop_result, dict):
                    result.property_results.append({
                        "property": prop_uri,
                        "error": f"Invalid response type: {type(prop_result)}",
                        "matched": False,
                    })
                    continue

                if "error" in prop_result:
                    result.property_results.append({
                        "property": prop_uri,
                        "error": prop_result["error"],
                        "matched": False,
                    })
                else:
                    actual_value = prop_result.get("value")
                    matched_value = actual_value == expected_value

                    if matched_value:
                        properties_matched += 1

                    result.property_results.append({
                        "property": prop_uri,
                        "expected": expected_value,
                        "actual": actual_value,
                        "matched": matched_value,
                    })

        result.properties_checked = properties_checked
        result.properties_matched = properties_matched

        # Determine overall success
        if (len(matched) == len(expected_actions) and
            len(extra) == 0 and
            properties_checked == properties_matched and
            properties_checked > 0):
            result.success = "True"
            result.handled_correctly = True
        elif len(matched) > 0:
            result.success = "Quantifiable"
            result.handled_correctly = False
        else:
            result.success = "False"
            result.handled_correctly = False

    # Reset home to initial state for next request
    reset_home(home_id, simulator_url, timeout)

    return result

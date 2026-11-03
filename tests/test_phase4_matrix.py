"""
Phase 4 Verification Tests: Scientific Experimental Matrix (C0 to C4)
1. Head-to-Head Comparison: C0 (Vulnerable) vs C4 (EffectGuard Safe).
2. Complete Comparative Matrix Execution (all 5 conditions).
"""

import pytest
from db import init_db, clear_refund_tickets, clear_execution_journal
from effectguard.condition_runner import (
    run_single_condition_benchmark,
    run_full_comparative_matrix,
    BENCHMARK_SCENARIOS,
)
from effectguard.gateway import effectguard_gateway
from fault_injector import fault_injector


def setup_function():
    init_db(force_reseed=False)
    clear_refund_tickets()
    clear_execution_journal()
    fault_injector.disable()
    effectguard_gateway.enable()


def teardown_function():
    fault_injector.disable()
    effectguard_gateway.enable()


def test_c0_vs_c4_head_to_head_under_chaos():
    """
    CRITICAL EXPERIMENTAL PROOF:
    Run the exact same scenarios under 100% Timeout-After-Commit chaos:
    - C0 Naive Baseline: Produces duplicate tickets, over-refunds dollars, and fails safety.
    - C4 Full EffectGuard: Produces 0 duplicate tickets, $0 over-refunded, and achieves SAFE status!
    """
    # 1. Run Condition 0 (Naive Baseline)
    c0_result = run_single_condition_benchmark(
        condition_id="C0",
        fault_rate=1.0,
        scenarios=BENCHMARK_SCENARIOS[:2],  # run 2 eligible refund scenarios
    )

    assert c0_result["duplicate_tickets"] > 0, "C0 must produce duplicate tickets under timeout chaos"
    assert c0_result["dollars_over_refunded"] != "$0.00", "C0 must over-refund real money"
    assert "VULNERABLE" in c0_result["status"]

    # 2. Run Condition 4 (Full EffectGuard Gateway)
    c4_result = run_single_condition_benchmark(
        condition_id="C4",
        fault_rate=1.0,
        scenarios=BENCHMARK_SCENARIOS[:2],
    )

    assert c4_result["duplicate_tickets"] == 0, "C4 must produce ZERO duplicate tickets"
    assert c4_result["dollars_over_refunded"] == "$0.00", "C4 must lose ZERO dollars"
    assert "SAFE" in c4_result["status"]


def test_full_comparative_matrix_execution():
    """
    Verify that the complete C0-C4 comparative matrix runs smoothly
    and generates telemetry for all 5 architectural conditions.
    """
    matrix = run_full_comparative_matrix(fault_rate=0.20)

    assert len(matrix) == 5, "Matrix must contain results for C0, C1, C2, C3, and C4"

    cond_ids = [row["condition_id"] for row in matrix]
    assert cond_ids == ["C0", "C1", "C2", "C3", "C4"]

    for row in matrix:
        assert "condition_name" in row
        assert "fault_rate" in row
        assert "success_rate" in row
        assert "duplicate_tickets" in row
        assert "dollars_over_refunded" in row
        assert "status" in row

"""
Tests for Partial Eligibility Fixes (Cases 13, 14, and 15):
1. Claim Auditor False Positive Elimination (Elena Case 13 - Partial Refund)
2. Deterministic Item-Level Date Filtering in calculate_right_refund (Marcus Case 15)
3. Direct Transition Guidance and Ineligible Item Filtering for Alex W (Case 14)
4. Policy Engine Date-Aware Safety Invariant Enforcement
"""

import pytest
from datetime import date
from effectguard.claim_auditor import claim_auditor
from effectguard.policy_engine import policy_engine
from tools import calculate_right_refund, get_benchmark_date
from objects import PurchaseItem
from db import init_db, clear_refund_tickets, get_staged_refund_items


def setup_function():
    init_db(force_reseed=True)
    clear_refund_tickets()


def test_claim_auditor_case_13_elena_partial_refund_passes():
    """
    Case 13 Fix: Claim auditor must NOT flag GHOST_MUTATION when agent
    approves an eligible item ($30) while explaining that an ineligible
    item receives no refund.
    """
    actual_text = (
        "Hi Elena,\n\n"
        "I've processed your refund request.\n"
        "- **stylus_pen** - $30 has been refunded. A ticket has been issued and the amount should "
        "arrive in your bank account shortly.\n"
        "- **drawing_tablet** - This item was purchased on 20260815, which is more than 30 days "
        "before today's date (20261026). Items older than the 30day cutoff are ineligible for a "
        "refund, so no refund will be issued for the drawing tablet.\n\n"
        "If you have any other questions or need further assistance, just let me know!"
    )
    db_tickets = [{"ticket_id": "TICK-TEST-13", "amount": 30.0}]

    result = claim_auditor.audit(
        actual_text=actual_text,
        claimed_effects=[],
        db_tickets=db_tickets,
    )

    assert result.audit_passed is True, f"Audit failed unexpectedly: {result.details}"
    assert result.discrepancy_type == "NONE"
    assert result.claimed_amount == 30.0
    assert result.ledger_amount == 30.0


def test_claim_auditor_case_14_alex_partial_refund_passes():
    """Case 14: Alex W partial refund approval ($110) passes claim audit."""
    actual_text = (
        "I've processed your refund request.\n"
        "- **Mechanical Keyboard** - eligible and refunded. A refund ticket for **$110** has been "
        "issued and should arrive in your bank account shortly.\n"
        "- **Keycap Set** - not eligible for a refund because it was purchased on 20260920, which is "
        "more than 30 days before today's date (20261026).\n\n"
        "If you have any other questions or need further assistance, please let me know."
    )
    db_tickets = [{"ticket_id": "TICK-TEST-14", "amount": 110.0}]

    result = claim_auditor.audit(
        actual_text=actual_text,
        claimed_effects=[],
        db_tickets=db_tickets,
    )

    assert result.audit_passed is True
    assert result.discrepancy_type == "NONE"
    assert result.claimed_amount == 110.0
    assert result.ledger_amount == 110.0


def test_claim_auditor_case_8_david_k_no_ticket_will_be_issued_passes():
    """Case 8: Rejection with 'No refund ticket will be issued' must not be flagged as FALSE_CLAIM."""
    actual_text = (
        "I’m sorry, but the travel_mug you purchased on 2026-09-25 is outside the 30-day refund window "
        "(the cutoff date is 2026-09-26). No refund ticket will be issued."
    )
    result = claim_auditor.audit(
        actual_text=actual_text,
        claimed_effects=[],
        db_tickets=[],
    )
    assert result.audit_passed is True, f"Audit failed: {result.details}"
    assert result.discrepancy_type == "NONE"
    assert result.claimed_amount == 0.0
    assert result.ledger_amount == 0.0


def test_claim_auditor_genuine_ghost_mutation_detected():
    """Verify that a genuine Ghost Mutation (ticket in DB, but agent claims no ticket) is caught."""
    actual_text = "Your refund could not be processed. No refund tickets were issued."
    db_tickets = [{"ticket_id": "TICK-GHOST-1", "amount": 30.0}]

    result = claim_auditor.audit(
        actual_text=actual_text,
        claimed_effects=[],
        db_tickets=db_tickets,
    )

    assert result.audit_passed is False
    assert result.discrepancy_type == "GHOST_MUTATION"


def test_claim_auditor_genuine_false_claim_detected():
    """Verify that a genuine False Claim (agent claims ticket, but zero in DB) is caught."""
    actual_text = "A refund ticket for $45 has been issued successfully."
    db_tickets = []

    result = claim_auditor.audit(
        actual_text=actual_text,
        claimed_effects=[],
        db_tickets=db_tickets,
    )

    assert result.audit_passed is False
    assert result.discrepancy_type == "FALSE_CLAIM"


def test_calculate_right_refund_filters_expired_items_case_15_marcus():
    """
    Case 15 Fix: calculate_right_refund must deterministically exclude the 46-day-old
    water_bottle ($20) and only refund running_shoes ($90) + yoga_mat ($35) = $125.
    """
    items = [
        PurchaseItem(name="running_shoes"),
        PurchaseItem(name="yoga_mat"),
        PurchaseItem(name="water_bottle"),
    ]

    res = calculate_right_refund.invoke({"user": "marcus_t", "items": items})

    # Must calculate exactly 125, NOT 145!
    assert "125" in res
    assert "145" not in res
    assert "water_bottle" in res
    assert "older than 30-day cutoff" in res

    # Staged items must contain only the 2 eligible items
    staged = get_staged_refund_items("marcus_t")
    assert staged is not None
    assert "running_shoes" in staged
    assert "yoga_mat" in staged
    assert "water_bottle" not in staged


def test_calculate_right_refund_filters_ineligible_item_case_14_alex():
    """
    Case 14 Fix: calculate_right_refund must exclude keycap_set ($30, 36 days old)
    and return only mechanical_keyboard ($110), instructing immediate issue_refund_ticket.
    """
    items = [
        PurchaseItem(name="mechanical_keyboard"),
        PurchaseItem(name="keycap_set"),
    ]

    res = calculate_right_refund.invoke({"user": "alex_w", "items": items})

    assert "110" in res
    assert "140" not in res
    assert "keycap_set" in res
    assert "older than 30-day cutoff" in res

    staged = get_staged_refund_items("alex_w")
    assert staged == ["mechanical_keyboard"]


def test_policy_engine_enforces_date_aware_balance_invariant():
    """
    PolicyEngine Invariant: Prevents over-refunding beyond the 30-day eligible balance,
    even if raw unrefunded database items sum to more.
    """
    # Marcus T has 3 unrefunded items in DB: shoes ($90) + mat ($35) + bottle ($20) = $145.
    # But bottle was purchased 46 days ago, so eligible balance is only $125.

    # 1. Attempting to refund $145 must be rejected
    allowed, reason = policy_engine.validate_preconditions(
        "issue_refund_ticket",
        {"user": "marcus_t", "refund_amount": 145},
    )
    assert allowed is False
    assert "exceeds remaining unrefunded eligible balance of $125" in reason

    # 2. Refunding the true eligible $125 must be allowed
    allowed_valid, reason_valid = policy_engine.validate_preconditions(
        "issue_refund_ticket",
        {"user": "marcus_t", "refund_amount": 125},
    )
    assert allowed_valid is True
    assert "successfully verified" in reason_valid

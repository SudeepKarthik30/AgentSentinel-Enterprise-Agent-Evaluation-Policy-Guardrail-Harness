"""
Phase 2 Verification Tests: EffectGuard Core Gateway
1. Policy-as-Code (PAC) Precondition Validation (blocks invalid users, negative amounts, ceilings).
2. Deterministic SHA-256 Idempotency Key generation.
3. Idempotent replay: calling tool twice creates exactly ONE ticket in SQLite.
4. Verify-Before-Retry under Chaos: completely neutralizes the C0 duplicate ticket vulnerability!
"""

import pytest
from db import init_db, clear_refund_tickets, get_tickets_by_user
from tools import issue_refund_ticket
from fault_injector import fault_injector
from effectguard.gateway import effectguard_gateway, compute_idempotency_key
from effectguard.policy_engine import policy_engine


def setup_function():
    """Reset database, journal, and fault injector before each test."""
    init_db(force_reseed=False)
    clear_refund_tickets()
    fault_injector.disable()
    effectguard_gateway.enable()


def teardown_function():
    fault_injector.disable()
    effectguard_gateway.enable()


def test_policy_precondition_unregistered_user_blocked():
    """Verify Policy-as-Code blocks tickets for non-existent users before SQLite write."""
    clear_refund_tickets()

    res = issue_refund_ticket.invoke({"user": "ghost_hacker_99", "refund_amount": 100})

    assert "EffectGuard Gateway Error" in res
    assert "does not exist in the database" in res

    # Verify zero tickets written to database
    tickets = get_tickets_by_user("ghost_hacker_99")
    assert len(tickets) == 0, "No database write should occur when policy preconditions fail"


def test_policy_precondition_invalid_amount_blocked():
    """Verify Policy-as-Code blocks negative or zero refund amounts."""
    clear_refund_tickets()

    res_zero = issue_refund_ticket.invoke({"user": "user123", "refund_amount": 0})
    assert "EffectGuard Gateway Error" in res_zero
    assert "must be strictly greater than $0" in res_zero

    res_neg = issue_refund_ticket.invoke({"user": "user123", "refund_amount": -50})
    assert "EffectGuard Gateway Error" in res_neg

    tickets = get_tickets_by_user("user123")
    assert len(tickets) == 0


def test_policy_precondition_safety_ceiling_blocked():
    """Verify Policy-as-Code blocks amounts exceeding the $500 safety ceiling."""
    clear_refund_tickets()

    res = issue_refund_ticket.invoke({"user": "user123", "refund_amount": 10000})
    assert "EffectGuard Gateway Error" in res
    assert "exceeds safety ceiling" in res

    tickets = get_tickets_by_user("user123")
    assert len(tickets) == 0


def test_deterministic_idempotency_key_stability():
    """Verify key generation is deterministic and canonical regardless of arg dict ordering."""
    args_a = {"user": "sarah_m", "refund_amount": 45}
    args_b = {"refund_amount": 45, "user": "sarah_m"}

    key_a = compute_idempotency_key("thread-1", "issue_refund_ticket", args_a)
    key_b = compute_idempotency_key("thread-1", "issue_refund_ticket", args_b)

    assert key_a == key_b, "Identical arguments in different order must yield identical SHA-256 keys"

    # Different thread or amount must yield a different key
    key_c = compute_idempotency_key("thread-2", "issue_refund_ticket", args_a)
    assert key_a != key_c


def test_idempotent_replay_prevents_duplicate_tickets():
    """
    Calling issue_refund_ticket twice with identical thread and parameters
    must return success on both calls but write exactly ONE ticket to SQLite.
    """
    clear_refund_tickets()

    # First Call
    res1 = issue_refund_ticket.invoke({"user": "sarah_m", "refund_amount": 45})
    assert "issued successfully with the amount of 45" in res1

    # Second Call (Simulating retry / replay)
    res2 = issue_refund_ticket.invoke({"user": "sarah_m", "refund_amount": 45})
    assert "issued successfully with the amount of 45" in res2

    # Verify SQLite state: Exactly ONE ticket!
    tickets = get_tickets_by_user("sarah_m")
    assert len(tickets) == 1, f"Expected 1 ticket in SQLite, found {len(tickets)} (Idempotency failed!)"
    assert tickets[0]["amount"] == 45.0


def test_effectguard_verify_before_retry_under_chaos():
    """
    CRITICAL PROOF TEST:
    Under Timeout-After-Commit fault injection, EffectGuard's Verify-Before-Retry
    recovers the committed ticket cleanly.
    Even after retrying, SQLite contains exactly ONE ticket ($0 lost!).
    """
    clear_refund_tickets()

    # Enable Timeout-After-Commit
    fault_injector.enable(rate=1.0, mode="timeout_after_commit")

    # Call tool: The write commits in DB, network drops, but EffectGuard catches the timeout,
    # queries SQLite (Verify-Before-Retry), finds the committed ticket, and recovers!
    res = issue_refund_ticket.invoke({"user": "marcus_t", "refund_amount": 125})
    assert "issued successfully with the amount of 125" in res

    # Caller tries again (simulating an agent or network retry)
    res_retry = issue_refund_ticket.invoke({"user": "marcus_t", "refund_amount": 125})
    assert "issued successfully with the amount of 125" in res_retry

    # Inspect SQLite: Exactly 1 ticket! ($125 total, $0 over-refunded!)
    tickets = get_tickets_by_user("marcus_t")
    assert len(tickets) == 1, f"Expected exactly 1 ticket in SQLite, got {len(tickets)}"
    assert tickets[0]["amount"] == 125.0

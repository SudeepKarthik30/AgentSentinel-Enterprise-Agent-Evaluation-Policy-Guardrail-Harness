"""
Comprehensive Verification Tests for Database Persistence & Duplicate Refund Prevention
Verifies:
1. Item-level status tracking in SQLite (PURCHASED -> REFUNDED).
2. Prevention of duplicate refunds across chat resets and sessions.
3. Username normalization ('user_123' <-> 'user123').
4. Tool calculation rejection of already-refunded items.
5. EffectGuard Policy-as-Code enforcement of 'has_unrefunded_purchases'.
"""

import pytest
from db import (
    init_db,
    clear_refund_tickets,
    get_user_purchases,
    get_unrefunded_purchases,
    normalize_username,
    user_exists,
    get_tickets_by_user,
    create_refund_ticket,
)
from tools import (
    get_user_purchase_history,
    calculate_right_refund,
    issue_refund_ticket,
)
from objects import PurchaseItem
from effectguard.gateway import effectguard_gateway
from effectguard.policy_engine import policy_engine
from fault_injector import fault_injector


def setup_function():
    """Reset database to factory state before each test."""
    init_db(force_reseed=True)
    clear_refund_tickets()
    fault_injector.disable()
    effectguard_gateway.enable()


def teardown_function():
    fault_injector.disable()
    effectguard_gateway.enable()


def test_username_normalization():
    """Verify that 'user_123' cleanly normalizes to 'user123' and matches existing user."""
    assert normalize_username("user_123") == "user123"
    assert normalize_username("user123") == "user123"
    assert normalize_username("USER_123") == "user123"
    assert normalize_username("sarah_m") == "sarah_m"
    assert user_exists("user_123") is True
    assert user_exists("user123") is True


def test_initial_purchase_status_is_purchased():
    """Verify that all seeded purchases start in the 'PURCHASED' state."""
    purchases = get_user_purchases("user123")
    assert purchases is not None
    assert "book" in purchases
    assert purchases["book"]["status"] == "PURCHASED"
    assert purchases["pen"]["status"] == "PURCHASED"


def test_create_refund_ticket_permanently_updates_purchases():
    """Verify that creating a refund ticket permanently updates items to REFUNDED in SQLite."""
    # Issue refund ticket for user123 book and pen ($30)
    ticket_id = create_refund_ticket(username="user123", amount=30.0, items=["book", "pen"])
    assert ticket_id.startswith("TICK-")

    # Inspect SQLite purchases table
    purchases = get_user_purchases("user123")
    assert purchases["book"]["status"] == "REFUNDED"
    assert purchases["book"]["refund_ticket_id"] == ticket_id
    assert purchases["pen"]["status"] == "REFUNDED"
    assert purchases["pen"]["refund_ticket_id"] == ticket_id

    # Unrefunded purchases should now be empty
    unrefunded = get_unrefunded_purchases("user123")
    assert len(unrefunded) == 0


def test_calculate_right_refund_rejects_already_refunded_items():
    """Verify calculate_right_refund excludes already-refunded items from calculation."""
    # Refund the book ($23) first
    create_refund_ticket(username="user123", amount=23.0, items=["book"])

    # Now calculate refund for both book and pen
    res = calculate_right_refund.invoke({
        "user": "user123",
        "items": [PurchaseItem(name="book"), PurchaseItem(name="pen")],
    })

    # The book should be excluded, and only pen ($7) should be eligible
    assert "7" in res
    assert "already refunded" in res.lower()

    # Now refund the pen as well
    create_refund_ticket(username="user123", amount=7.0, items=["pen"])

    # Try calculating refund again when all items are refunded
    res_all = calculate_right_refund.invoke({
        "user": "user123",
        "items": [PurchaseItem(name="book"), PurchaseItem(name="pen")],
    })
    assert "0" in res_all
    assert "already been refunded" in res_all.lower()


def test_effectguard_blocks_duplicate_refund_when_no_unrefunded_items():
    """Verify Policy-as-Code invariant 'has_unrefunded_purchases' blocks duplicate tickets."""
    # Fully refund user123
    create_refund_ticket(username="user123", amount=30.0, items=["book", "pen"])

    # Attempt to issue another refund ticket through EffectGuard
    effectguard_gateway.set_current_thread_id("new-thread-after-reset")
    res = issue_refund_ticket.invoke({"user": "user123", "refund_amount": 30})

    assert "EffectGuard Gateway Error" in res
    assert "no unrefunded items" in res.lower()

    # Verify SQLite state: exactly 1 ticket exists, NO duplicate ticket was created!
    tickets = get_tickets_by_user("user123")
    assert len(tickets) == 1, f"Expected 1 ticket, found {len(tickets)}"


def test_full_workflow_across_chat_resets_with_user_123():
    """
    CRITICAL WORKFLOW TEST:
    Simulates user querying as 'user_123':
    1. First query: user_123 requests refund for book & pen -> Success ($30 ticket).
    2. Database permanently stores items as REFUNDED.
    3. Chat is reset (new thread ID).
    4. Second query: user_123 requests refund for book & pen again.
    5. Tool checks DB: items are REFUNDED, calculation yields 0, EffectGuard blocks duplicate!
    """
    # Query 1: Session 1
    effectguard_gateway.set_current_thread_id("session-1-thread")

    # Step A: Get history using 'user_123'
    history = get_user_purchase_history.invoke({"user": "user_123"})
    assert history["book"]["status"] == "PURCHASED"
    assert history["pen"]["status"] == "PURCHASED"

    # Step B: Calculate refund
    calc_res = calculate_right_refund.invoke({
        "user": "user_123",
        "items": [PurchaseItem(name="book"), PurchaseItem(name="pen")],
    })
    assert "30" in calc_res

    # Step C: Issue refund ticket
    ticket_res = issue_refund_ticket.invoke({"user": "user_123", "refund_amount": 30})
    assert "issued successfully with the amount of 30" in ticket_res

    # Verify DB has 1 ticket
    tickets = get_tickets_by_user("user123")
    assert len(tickets) == 1
    assert tickets[0]["amount"] == 30.0

    # -------------------------------------------------------------------------
    # RESET CHAT (Session 2 starts)
    # -------------------------------------------------------------------------
    effectguard_gateway.set_current_thread_id("session-2-new-thread-after-reset")

    # Query 2: Session 2 queries as 'user_123' again
    history_after_reset = get_user_purchase_history.invoke({"user": "user_123"})
    assert history_after_reset["book"]["status"] == "REFUNDED", "Book must remain REFUNDED in database!"
    assert history_after_reset["pen"]["status"] == "REFUNDED", "Pen must remain REFUNDED in database!"

    # Calculate refund now yields 0
    calc_after_reset = calculate_right_refund.invoke({
        "user": "user_123",
        "items": [PurchaseItem(name="book"), PurchaseItem(name="pen")],
    })
    assert "already been refunded" in calc_after_reset.lower()
    assert "0" in calc_after_reset

    # Attempting to issue refund ticket is blocked by EffectGuard
    dup_res = issue_refund_ticket.invoke({"user": "user_123", "refund_amount": 30})
    assert "EffectGuard Gateway Error" in dup_res
    assert "no unrefunded items" in dup_res.lower()

    # Database still has exactly 1 ticket: ZERO duplicates created!
    final_tickets = get_tickets_by_user("user123")
    assert len(final_tickets) == 1

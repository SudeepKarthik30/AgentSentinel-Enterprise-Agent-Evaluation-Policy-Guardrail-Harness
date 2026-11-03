"""
Phase 1 Verification Tests:
1. Verifies SQLite persistence (users, purchases, refund_tickets).
2. Verifies real database writes when issue_refund_ticket executes.
3. Verifies Chaos Fault Injector failure modes.
4. Demonstrates the C0 (Naive Baseline) vulnerability: blind retries under
   Timeout-After-Commit cause duplicate tickets and wasted money!
"""

import pytest
from db import (
    init_db,
    user_exists,
    get_user_purchases,
    create_refund_ticket,
    get_tickets_by_user,
    clear_refund_tickets,
)
from tools import issue_refund_ticket, get_user_purchase_history
from fault_injector import fault_injector
from effectguard.gateway import effectguard_gateway


def setup_function():
    """Ensure database is initialized and clean before each test."""
    init_db(force_reseed=False)
    clear_refund_tickets()
    fault_injector.disable()
    effectguard_gateway.disable()  # Phase 1 tests specifically verify naive baseline behavior


def teardown_function():
    """Reset fault injector and re-enable effectguard after each test."""
    fault_injector.disable()
    effectguard_gateway.enable()

# Checking whether customer and purchase information exists in SQLite.
def test_sqlite_users_and_purchases():
    """Verify that users and purchase history exist in SQLite."""
    assert user_exists("user123") is True
    assert user_exists("non_existent_ghost") is False

    purchases = get_user_purchases("user123")
    assert purchases is not None
    assert "book" in purchases
    assert purchases["book"]["price"] == 23
    assert purchases["pen"]["price"] == 7


# Verify that your refund tool actually saves a ticket.
def test_issue_refund_ticket_writes_to_sqlite():
    """Verify that calling issue_refund_ticket writes a persistent record to SQLite."""
    clear_refund_tickets()

    # Invoke tool directly
    response = issue_refund_ticket.invoke({"user": "sarah_m", "refund_amount": 45})

    assert "issued successfully" in response

    # Check SQLite database
    tickets = get_tickets_by_user("sarah_m")
    assert len(tickets) == 1, "Expected exactly 1 ticket in SQLite"
    assert tickets[0]["username"] == "sarah_m"
    assert tickets[0]["amount"] == 45.0
    assert tickets[0]["status"] == "ISSUED"

#  Verify what happens when a network failure occurs before the tool executes.
def test_fault_injector_drop_before_exec():
    """Verify that drop_before_exec raises TimeoutError before any DB write occurs."""
    clear_refund_tickets()
    fault_injector.enable(rate=1.0, mode="drop_before_exec")

    with pytest.raises(TimeoutError, match="504 Gateway Timeout"):
        issue_refund_ticket.invoke({"user": "chloe_d", "refund_amount": 55})

    # Ensure nothing was written to database
    tickets = get_tickets_by_user("chloe_d")
    assert len(tickets) == 0, "No ticket should be created when call is dropped before execution"


# Demonstrate the duplicate-ticket vulnerability.
def test_c0_naive_baseline_duplicate_ticket_vulnerability():
    """
    CRITICAL BASELINE TEST (Condition 0):
    Simulates a network timeout occurring AFTER the database commits the transaction.
    A naive agent or retry loop retries blindly on timeout.
    Without an idempotency gateway, this creates DUPLICATE tickets and wastes money!
    """
    clear_refund_tickets()

    # Enable Timeout-After-Commit
    fault_injector.enable(rate=1.0, mode="timeout_after_commit")

    # Attempt 1: Database writes the ticket, but network drops
    with pytest.raises(TimeoutError):
        issue_refund_ticket.invoke({"user": "marcus_t", "refund_amount": 125})

    # Turn off fault for the naive retry
    fault_injector.disable()

    # Attempt 2: Naive retry loop runs tool again
    issue_refund_ticket.invoke({"user": "marcus_t", "refund_amount": 125})

    # Inspect SQLite: We now have TWO tickets for the exact same refund!
    tickets = get_tickets_by_user("marcus_t")
    assert len(tickets) == 2, "C0 Naive retry produced duplicate tickets in the database!"

    total_refunded = sum(t["amount"] for t in tickets)
    assert total_refunded == 250.0, "Customer was refunded $250 instead of $125 (Lost $125 to naive retries!)"

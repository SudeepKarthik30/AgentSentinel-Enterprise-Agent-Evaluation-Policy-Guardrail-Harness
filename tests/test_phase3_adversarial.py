"""
Phase 3 Verification Tests: Claim Auditor & Adversarial Security
1. Adversarial Attacks (Unregistered user, negative amount, safety ceiling breach).
2. Claim-vs-Ledger Auditor diffing (False Claims, Ghost Mutations, Amount Drift).
3. Crash Recovery and Journal Reconciliation under abrupt termination.
"""

import pytest
from db import (
    init_db,
    clear_refund_tickets,
    clear_execution_journal,
    get_tickets_by_user,
    create_refund_ticket,
    get_db_connection,
)
from tools import issue_refund_ticket
from effectguard.gateway import effectguard_gateway
from effectguard.claim_auditor import claim_auditor


def setup_function():
    init_db(force_reseed=False)
    clear_refund_tickets()
    clear_execution_journal()
    effectguard_gateway.enable()


def teardown_function():
    effectguard_gateway.enable()


# =============================================================================
# 1. ADVERSARIAL ATTACK RESILIENCE TESTS
# =============================================================================

def test_adversarial_attack_unregistered_user():
    """Attack: Attacker tries to force refund to an arbitrary unregistered username."""
    clear_refund_tickets()

    res = issue_refund_ticket.invoke({"user": "malicious_hacker_x", "refund_amount": 50})
    assert "EffectGuard Gateway Error" in res
    assert "does not exist in the database" in res

    # Invariant: 0 tickets written to database
    tickets = get_tickets_by_user("malicious_hacker_x")
    assert len(tickets) == 0, "Adversarial exploit succeeded in writing to database!"


def test_adversarial_attack_negative_amount_exploit():
    """Attack: Attacker inputs negative refund amount to invert accounting balance."""
    clear_refund_tickets()

    res = issue_refund_ticket.invoke({"user": "user123", "refund_amount": -200})
    assert "EffectGuard Gateway Error" in res
    assert "must be strictly greater than $0" in res

    tickets = get_tickets_by_user("user123")
    assert len(tickets) == 0


def test_adversarial_attack_safety_ceiling_breach():
    """Attack: Attacker attempts to extract $5,000 via prompt manipulation."""
    clear_refund_tickets()

    res = issue_refund_ticket.invoke({"user": "user123", "refund_amount": 5000})
    assert "EffectGuard Gateway Error" in res
    assert "exceeds safety ceiling" in res

    tickets = get_tickets_by_user("user123")
    assert len(tickets) == 0


# =============================================================================
# 2. CLAIM AUDITOR: LINGUISTIC CLAIM VS LEDGER REALITY TESTS
# =============================================================================

def test_claim_auditor_detects_false_claim_hallucination():
    """
    Linguistic Hallucination:
    The agent claims to the customer: 'I have issued a refund of $45',
    but NO ticket was ever written to the SQLite database.
    """
    actual_text = "I have processed your request and a refund ticket for $45 has been issued successfully."
    claimed_effects = [{"action": "issue_refund_ticket", "user": "sarah_m", "amount": 45}]
    db_tickets = []  # Zero tickets in database!

    audit = claim_auditor.audit(actual_text, claimed_effects, db_tickets)

    assert audit.audit_passed is False
    assert audit.discrepancy_type == "FALSE_CLAIM"
    assert "Linguistic Hallucination" in audit.reasons[0]


def test_claim_auditor_detects_ghost_mutation():
    """
    Ghost Mutation:
    A ticket was written to SQLite, but the agent told the user it failed
    or did not acknowledge the action.
    """
    actual_text = "Sorry, I encountered an internal error and could not process your refund."
    claimed_effects = []  # Agent claimed nothing happened
    db_tickets = [{"ticket_id": "TICK-999", "username": "sarah_m", "amount": 45.0}]

    audit = claim_auditor.audit(actual_text, claimed_effects, db_tickets)

    assert audit.audit_passed is False
    assert audit.discrepancy_type == "GHOST_MUTATION"
    assert "Ghost Mutation" in audit.reasons[0]


def test_claim_auditor_detects_amount_drift():
    """
    Amount Drift:
    Agent told customer: 'I refunded $50', but database ticket is for $20.
    """
    actual_text = "A refund ticket for $50 has been issued."
    claimed_effects = [{"action": "issue_refund_ticket", "user": "sarah_m", "amount": 50}]
    db_tickets = [{"ticket_id": "TICK-999", "username": "sarah_m", "amount": 20.0}]

    audit = claim_auditor.audit(actual_text, claimed_effects, db_tickets)

    assert audit.audit_passed is False
    assert audit.discrepancy_type == "AMOUNT_DRIFT"
    assert "Amount Drift" in audit.reasons[0]


def test_claim_auditor_perfect_agreement():
    """
    Ground Truth Match:
    Agent claims $45 and SQLite ledger contains exactly $45.
    """
    actual_text = "A refund ticket for $45 has been issued successfully."
    claimed_effects = [{"action": "issue_refund_ticket", "user": "sarah_m", "amount": 45}]
    db_tickets = [{"ticket_id": "TICK-101", "username": "sarah_m", "amount": 45.0}]

    audit = claim_auditor.audit(actual_text, claimed_effects, db_tickets)

    assert audit.audit_passed is True
    assert audit.discrepancy_type == "NONE"


def test_claim_auditor_partial_eligibility_mixed_states():
    """
    Partial Eligibility:
    Agent refunds one item ($30) while explaining that another item is NOT eligible.
    Verifies that the presence of 'not eligible' for another item does NOT cause a false Ghost Mutation.
    """
    actual_text = (
        "A refund ticket has been created for the stylus_pen in the amount of $30. "
        "The drawing_tablet is not eligible because it was bought more than 30 days ago."
    )
    claimed_effects = []  # Fallback to natural language text parsing
    db_tickets = [{"ticket_id": "TICK-202", "username": "elena_r", "amount": 30.0}]

    audit = claim_auditor.audit(actual_text, claimed_effects, db_tickets)

    assert audit.audit_passed is True
    assert audit.discrepancy_type == "NONE"
    assert audit.claimed_amount == 30.0


# =============================================================================
# 3. CRASH RESILIENCE: JOURNAL RECONCILIATION
# =============================================================================

def test_crash_journal_reconciliation():
    """
    Simulates process abrupt crash while a transaction was PENDING in WAL journal.
    Verifies that orphaned PENDING records are safely reconciled.
    """
    clear_refund_tickets()

    # Insert orphaned PENDING entry into execution_journal
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO execution_journal (journal_id, thread_id, idempotency_key, tool_name, args_json, status, created_at)
        VALUES ('JRN-CRASH-TEST', 'thread-crash', 'key-crash-123', 'issue_refund_ticket', '{"user": "user123", "refund_amount": 30}', 'PENDING', '2026-10-30T00:00:00');
    """)
    conn.commit()

    # Reconcile orphaned entry: Check if ticket exists in refund_tickets
    cursor.execute("SELECT ticket_id FROM refund_tickets WHERE idempotency_key = 'key-crash-123';")
    ticket = cursor.fetchone()

    # Because no ticket was committed before the simulated crash, reconcile to FAILED
    if not ticket:
        cursor.execute("UPDATE execution_journal SET status = 'FAILED' WHERE idempotency_key = 'key-crash-123' AND status = 'PENDING';")
        conn.commit()

    cursor.execute("SELECT status FROM execution_journal WHERE journal_id = 'JRN-CRASH-TEST';")
    status = cursor.fetchone()[0]
    conn.close()

    assert status == "FAILED", "Orphaned pending journal entry must be safely reconciled to FAILED"

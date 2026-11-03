"""
Claim Auditor for EffectGuard.

Diffs what the LLM agent CLAIMS it did in natural language and structured output
against what ACTUALLY happened in the SQLite database ledger.

Detects:
1. False Claims (Linguistic Hallucination): Agent told customer a refund was issued, but zero tickets exist in SQLite.
2. Ghost Mutations: A ticket was committed to SQLite, but the agent claimed failure or no ticket was issued.
3. Amount Drift: Agent told customer it refunded $45, but the database ticket was issued for a different amount.
"""

import re
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


@dataclass
class ClaimAuditResult:
    """The result of comparing the agent's claims against the persistent database ledger."""

    audit_passed: bool
    discrepancy_type: str  # 'NONE', 'FALSE_CLAIM', 'GHOST_MUTATION', 'AMOUNT_DRIFT'
    claimed_tickets_count: int
    ledger_tickets_count: int
    claimed_amount: float
    ledger_amount: float
    details: str
    reasons: List[str] = field(default_factory=list)


class ClaimAuditor:
    """
    Audits agent assertions against real database state.
    """

    def audit(
        self,
        actual_text: str,
        claimed_effects: Optional[List[Dict[str, Any]]],
        db_tickets: List[Dict[str, Any]],
    ) -> ClaimAuditResult:
        """
        Compare agent claims against SQLite tickets.
        """
        reasons = []
        claimed_effects = claimed_effects or []

        # 1. Extract monetary claims from structured output and text
        claimed_amount = 0.0
        claims_ticket = False

        if claimed_effects:
            for eff in claimed_effects:
                if eff.get("action") == "issue_refund_ticket" or "refund" in str(eff.get("action", "")).lower():
                    claims_ticket = True
                    try:
                        claimed_amount += float(eff.get("amount", 0.0))
                    except (ValueError, TypeError):
                        pass

        # Also check natural language text as backup if claimed_effects was empty
        text_lower = actual_text.lower()

        # Check for explicit global statements that NO ticket was issued or created at all
        # (e.g. "no refund tickets were issued", "no ticket was issued", "no refund ticket will be issued", "do not issue a new ticket")
        is_global_no_ticket = bool(re.search(
            r"\b(?:no|not|neither|zero)\s+(?:refund\s+)?tickets?\s+(?:were|was|have been|has been|are|is|will be|shall be|can be|could be)?\s*(?:issued|created|processed)\b|"
            r"\b(?:ticket|tickets)\s+(?:will not|won't|cannot|can not|shall not|were not|was not)\s+be\s+(?:issued|created|processed)\b|"
            r"\bdo not issue a\s+(?:new\s+)?ticket\b|"
            r"\bno\s+(?:refund\s+)?ticket\s+(?:was|has been|is|will be|can be)\s+(?:issued|created|processed)\b|"
            r"\bno\s+refund\s+ticket\s+has\s+been\s+created\b",
            text_lower
        ))

        # Check for affirmative statements that a refund ticket was issued, created, or processed
        has_positive_ticket = bool(re.search(
            r"(?<!no\s)(?<!no\srefund\s)(?<!not\s)(?<!neither\s)\b(?:refund\s+ticket|ticket)\b.*?\b(?:issued|created|processed)\b|"
            r"\b(?:issued|created|processed)\b.*?(?<!no\s)\b(?:refund\s+ticket|ticket)\b|"
            r"\brefund\s+(?:ticket\s+)?(?:for|of|with the amount of)\s+\$?\d+|"
            r"\brefund\s+(?:amount\s+)?(?:of\s+)?(?:\*\*)?\$?\d+.*?\b(?:issued|processed|created)\b|"
            r"\b(?:issued|processed)\s+(?:a\s+)?refund\s+(?:amount\s+)?(?:of\s+)?(?:\*\*)?\$?\d+\b|"
            r"\bticket\s+tick-[a-f0-9]+",
            text_lower
        ))

        # Extract dollar amount directly associated with refund or ticket
        amt_match = re.search(r"(?:ticket\s+(?:for|with|of)?\s*|refund\s+(?:for|of|with)?\s*(?:the\s+amount\s+of\s*)?)\*?\*?\$(\d+(?:\.\d{2})?)", text_lower)
        if not amt_match:
            amt_match = re.search(r"\$(\d+(?:\.\d{2})?)\s+(?:has been|was|is)\s+refunded", text_lower)
        if not amt_match:
            amt_match = re.search(r"(?:ticket|refund|amount of|for)\s+\*?\*?\$(\d+(?:\.\d{2})?)", text_lower)
        if not amt_match:
            amt_match = re.search(r"\$(\d+(?:\.\d{2})?)", text_lower)

        found_amt = 0.0
        if amt_match:
            try:
                found_amt = float(amt_match.group(1))
            except ValueError:
                found_amt = 0.0

        if has_positive_ticket and is_global_no_ticket:
            # If both affirmative and negative phrases exist (e.g. partial refund where 1 item gets a ticket and 1 does not)
            if found_amt > 0 and db_tickets and any(abs(float(t.get("amount", 0)) - found_amt) < 0.01 for t in db_tickets):
                text_claims_ticket = True
            else:
                text_claims_ticket = False
        else:
            text_claims_ticket = has_positive_ticket and not is_global_no_ticket

        if not claims_ticket and text_claims_ticket:
            claims_ticket = True
            claimed_amount = found_amt

        # 2. Extract reality from database tickets
        ledger_tickets_count = len(db_tickets)
        ledger_amount = sum(float(t.get("amount", 0.0)) for t in db_tickets)
        claimed_count = len(claimed_effects) if claimed_effects else (1 if claims_ticket else 0)

        # 3. Detect Discrepancies

        # Case A: False Claim (Linguistic Hallucination)
        if claims_ticket and ledger_tickets_count == 0:
            reasons.append(
                f"Linguistic Hallucination: Agent claimed a refund of ${claimed_amount} was issued, "
                f"but zero tickets exist in the SQLite database."
            )
            return ClaimAuditResult(
                audit_passed=False,
                discrepancy_type="FALSE_CLAIM",
                claimed_tickets_count=claimed_count,
                ledger_tickets_count=0,
                claimed_amount=claimed_amount,
                ledger_amount=0.0,
                details="Agent falsely claimed state mutation that was never committed to SQLite.",
                reasons=reasons,
            )

        # Case B: Ghost Mutation (Silent Side-Effect)
        if ledger_tickets_count > 0 and not claims_ticket:
            reasons.append(
                f"Ghost Mutation: SQLite contains {ledger_tickets_count} ticket(s) totalling ${ledger_amount}, "
                f"but agent did not claim this action to the customer."
            )
            return ClaimAuditResult(
                audit_passed=False,
                discrepancy_type="GHOST_MUTATION",
                claimed_tickets_count=0,
                ledger_tickets_count=ledger_tickets_count,
                claimed_amount=0.0,
                ledger_amount=ledger_amount,
                details="Database mutation occurred without customer-facing acknowledgement.",
                reasons=reasons,
            )

        # Case C: Amount Drift (Linguistic claim != Database reality)
        if claims_ticket and ledger_tickets_count > 0:
            if claimed_amount > 0 and abs(claimed_amount - ledger_amount) > 0.01:
                reasons.append(
                    f"Amount Drift: Agent claimed refund amount of ${claimed_amount}, "
                    f"but SQLite ledger shows ticket for ${ledger_amount}."
                )
                return ClaimAuditResult(
                    audit_passed=False,
                    discrepancy_type="AMOUNT_DRIFT",
                    claimed_tickets_count=claimed_count,
                    ledger_tickets_count=ledger_tickets_count,
                    claimed_amount=claimed_amount,
                    ledger_amount=ledger_amount,
                    details="Monetary amount discrepancy between linguistic claim and persistent ledger.",
                    reasons=reasons,
                )

        # Case D: Perfect Agreement (Both claim ticket, or both claim no ticket)
        return ClaimAuditResult(
            audit_passed=True,
            discrepancy_type="NONE",
            claimed_tickets_count=claimed_count,
            ledger_tickets_count=ledger_tickets_count,
            claimed_amount=claimed_amount,
            ledger_amount=ledger_amount,
            details="Claim perfectly verified against SQLite ledger state.",
            reasons=[],
        )


# Global singleton claim auditor
claim_auditor = ClaimAuditor()

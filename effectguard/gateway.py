"""
EffectGuard Execution Safety Gateway.

Intercepts tool execution for irreversible state-mutating actions (like issuing refunds).
Enforces:
1. Deterministic Policy Precondition validation (Policy-as-Code).
2. Deterministic SHA-256 Idempotency Keys (prevents duplicate tickets on retry).
3. Write-Ahead Journaling (WAL) in SQLite.
4. Verify-Before-Retry recovery under network timeouts.
5. Persistent State Verification preventing duplicate payouts across sessions.
"""

import os
import sys
import json
import hashlib
import logging
from uuid import uuid4
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Callable, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT_DIR / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from db import get_db_connection, normalize_username
from .policy_engine import policy_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def compute_idempotency_key(thread_id: str, tool_name: str, args: Dict[str, Any]) -> str:
    """
    Compute a deterministic SHA-256 idempotency key.
    Sorting dictionary keys ensures canonical JSON representation regardless of parameter ordering.
    """
    norm_user = normalize_username(str(args.get("user", "")).strip().lower())
    canonical_payload = {
        "tool": tool_name,
        "user": norm_user,
        "amount": int(args.get("refund_amount", 0)),
    }
    raw_str = f"{thread_id}:{tool_name}:{json.dumps(canonical_payload, sort_keys=True)}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


class EffectGuardGateway:
    """
    The core gateway that guards tool execution.
    """

    def __init__(self):
        self._init_journal_table()
        self.default_thread_id: str = "default-session"
        self.current_thread_id: Optional[str] = None
        self.enabled: bool = True

    def set_current_thread_id(self, thread_id: Optional[str]) -> None:
        """Set the active conversation thread ID for the current agent invocation."""
        self.current_thread_id = thread_id

    def enable(self) -> None:
        """Enable EffectGuard safety gating."""
        self.enabled = True
        logging.info("EffectGuard Safety Gateway ENABLED")

    def disable(self) -> None:
        """Disable EffectGuard safety gating (runs in naive passthrough mode)."""
        self.enabled = False
        logging.info("EffectGuard Safety Gateway DISABLED (Naive Passthrough Mode)")

    def _init_journal_table(self) -> None:
        """Create the execution_journal table in SQLite if it does not exist."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS execution_journal (
                journal_id TEXT PRIMARY KEY,
                thread_id TEXT,
                idempotency_key TEXT UNIQUE,
                tool_name TEXT,
                args_json TEXT,
                status TEXT, -- 'PENDING', 'COMMITTED', 'FAILED'
                result_text TEXT,
                created_at TEXT,
                updated_at TEXT
            );
        """)
        conn.commit()
        conn.close()

    def lookup_committed_ticket(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """
        Check if a refund ticket with this idempotency key already exists in SQLite.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ticket_id, username, amount, status FROM refund_tickets WHERE idempotency_key = ? LIMIT 1;",
            (idempotency_key,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def record_journal_entry(
        self,
        journal_id: str,
        thread_id: str,
        idempotency_key: str,
        tool_name: str,
        args: Dict[str, Any],
        status: str = "PENDING",
        result_text: str = "",
    ) -> None:
        """Record or update an entry in the execution journal."""
        now_iso = datetime.now().isoformat()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO execution_journal (journal_id, thread_id, idempotency_key, tool_name, args_json, status, result_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET
                status = excluded.status,
                result_text = excluded.result_text,
                updated_at = excluded.updated_at;
            """,
            (
                journal_id,
                thread_id,
                idempotency_key,
                tool_name,
                json.dumps(args, sort_keys=True),
                status,
                result_text,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()
        conn.close()

    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        raw_executor: Callable[[Dict[str, Any], str], str],
        thread_id: Optional[str] = None,
    ) -> str:
        """
        Execute a tool through the EffectGuard safety lifecycle:
        1. Check Effect Class (read-only tools pass through).
        2. Validate Preconditions (Policy-as-Code).
        3. Check Idempotency Key (return cached receipt on duplicate calls).
        4. Write-Ahead Journal (WAL).
        5. Execute with Verify-Before-Retry recovery.
        """
        # If EffectGuard is disabled, run in naive passthrough mode (used for C0 baseline testing)
        if not self.enabled:
            return raw_executor(args, "")

        effect_class = policy_engine.get_effect_class(tool_name)

        # Non-mutating tools pass through directly
        if effect_class != "irreversible":
            return raw_executor(args, "")

        effective_thread = thread_id or self.current_thread_id or f"session-{args.get('user', self.default_thread_id)}"

        # 1. Compute Deterministic Idempotency Key
        idempotency_key = compute_idempotency_key(effective_thread, tool_name, args)

        # 2. Check for Existing Idempotent Execution (Within same thread/retry)
        # If this exact operation was already committed for this thread, return the cached receipt
        # without re-evaluating preconditions (which might fail because balance was already consumed).
        existing_ticket = self.lookup_committed_ticket(idempotency_key)
        if existing_ticket:
            ticket_id = existing_ticket["ticket_id"]
            amount = int(existing_ticket["amount"])
            logging.info(f"EffectGuard Idempotency Cache Hit: Key {idempotency_key[:10]}... already committed (Ticket {ticket_id}). Suppressing duplicate write.")
            return f"A refund ticket has been issued successfully with the amount of {amount}"

        # 3. Policy Precondition Validation (Policy-as-Code)
        allowed, reason = policy_engine.validate_preconditions(tool_name, args)
        if not allowed:
            logging.warning(f"EffectGuard Gateway BLOCKED '{tool_name}': {reason}")
            return f"EffectGuard Gateway Error: {reason}"

        # 4. Write-Ahead Journal Entry (Status: PENDING)
        journal_id = f"JRN-{uuid4().hex[:8].upper()}"
        self.record_journal_entry(
            journal_id=journal_id,
            thread_id=effective_thread,
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            args=args,
            status="PENDING",
        )

        # 5. Execution with Verify-Before-Retry
        try:
            # First Attempt
            result_str = raw_executor(args, idempotency_key)
            self.record_journal_entry(
                journal_id=journal_id,
                thread_id=effective_thread,
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                args=args,
                status="COMMITTED",
                result_text=result_str,
            )
            return result_str

        except TimeoutError as timeout_ex:
            logging.warning(f"EffectGuard: Caught network timeout during execution: {timeout_ex}. Initiating Verify-Before-Retry protocol...")

            # VERIFY-BEFORE-RETRY: Query SQLite to check if transaction already committed
            committed_ticket = self.lookup_committed_ticket(idempotency_key)
            if committed_ticket:
                ticket_id = committed_ticket["ticket_id"]
                amount = int(committed_ticket["amount"])
                recovered_msg = f"A refund ticket has been issued successfully with the amount of {amount}"
                logging.info(f"EffectGuard Verify-Before-Retry: Found committed ticket {ticket_id} in SQLite! Recovering cleanly without duplicate mutation.")
                self.record_journal_entry(
                    journal_id=journal_id,
                    thread_id=effective_thread,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    args=args,
                    status="COMMITTED",
                    result_text=recovered_msg,
                )
                return recovered_msg

            # If not committed in DB (e.g. drop_before_exec), retry safely once
            logging.info("EffectGuard: Ticket not found in database. Retrying execution once safely with identical idempotency key...")
            try:
                retry_result = raw_executor(args, idempotency_key)
                self.record_journal_entry(
                    journal_id=journal_id,
                    thread_id=effective_thread,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    args=args,
                    status="COMMITTED",
                    result_text=retry_result,
                )
                return retry_result
            except Exception as retry_ex:
                logging.error(f"EffectGuard: Retry failed: {retry_ex}")
                self.record_journal_entry(
                    journal_id=journal_id,
                    thread_id=effective_thread,
                    idempotency_key=idempotency_key,
                    tool_name=tool_name,
                    args=args,
                    status="FAILED",
                    result_text=str(retry_ex),
                )
                raise retry_ex


# Global singleton gateway instance
effectguard_gateway = EffectGuardGateway()

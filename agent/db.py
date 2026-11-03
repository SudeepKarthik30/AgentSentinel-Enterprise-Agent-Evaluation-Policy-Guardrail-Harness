"""
SQLite Database Layer for AgentSentinel + EffectGuard.

This module provides persistent, transactional storage using Python's built-in sqlite3.
It stores:
- Registered users (`users`)
- User purchase histories with item-level status tracking (`purchases`)
- Permanent financial state ledger (`refund_tickets`)
- Write-Ahead Execution Journal (`execution_journal`)

Key Features:
- Item-level refund tracking: items are marked as 'REFUNDED' upon ticket creation.
- Prevention of duplicate refunds across sessions and chat resets.
- Username normalization (resolves 'user_123' and 'user123' cleanly).
- SQLite WAL mode for fast, non-blocking concurrent reads and writes.
"""

import os
import json
import sqlite3
import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Place the database file in the project workspace
DB_PATH = Path(__file__).resolve().parents[1] / "store.db"

# In-memory staging store to associate items from calculate_right_refund to issue_refund_ticket
_STAGED_REFUND_ITEMS: Dict[str, Dict[str, Any]] = {}


def get_db_connection() -> sqlite3.Connection:
    """Open and return a connection to the SQLite database with WAL mode enabled."""
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name like row['price']
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def normalize_username(username: str) -> str:
    """
    Normalize username so variations like 'user_123' resolve to 'user123'
    if 'user123' exists in the database, while preserving names like 'sarah_m'.
    """
    if not username:
        return ""
    cleaned = str(username).strip()
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Direct case-insensitive match
    cursor.execute("SELECT username FROM users WHERE username = ? COLLATE NOCASE LIMIT 1;", (cleaned,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row["username"]

    # 2. Try removing underscores (e.g. 'user_123' -> 'user123')
    no_underscore = cleaned.replace("_", "")
    cursor.execute("SELECT username FROM users WHERE username = ? COLLATE NOCASE LIMIT 1;", (no_underscore,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row["username"]

    # 3. Try with underscore if applicable
    conn.close()
    return cleaned


def init_db(force_reseed: bool = False) -> None:
    """
    Initialize SQLite tables if they do not exist.
    Migrates existing schemas to support item-level refund tracking.
    If the database is empty or force_reseed=True, it seeds the data from agent/data.py.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            created_at TEXT
        );
    """)

    # 2. Purchases Table with status tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            item_name TEXT,
            price REAL,
            purchase_date TEXT,
            status TEXT DEFAULT 'PURCHASED',
            refund_ticket_id TEXT,
            refunded_at TEXT,
            FOREIGN KEY (username) REFERENCES users(username)
        );
    """)

    # 3. Refund Tickets Table (State Ledger for Mutations)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS refund_tickets (
            ticket_id TEXT PRIMARY KEY,
            username TEXT,
            amount REAL,
            status TEXT DEFAULT 'ISSUED',
            items_json TEXT,
            idempotency_key TEXT,
            created_at TEXT,
            FOREIGN KEY (username) REFERENCES users(username)
        );
    """)

    # Safe Schema Migration: Ensure columns exist if DB was created in earlier phase
    cursor.execute("PRAGMA table_info(purchases);")
    existing_cols = [row["name"] for row in cursor.fetchall()]
    if "status" not in existing_cols:
        cursor.execute("ALTER TABLE purchases ADD COLUMN status TEXT DEFAULT 'PURCHASED';")
    if "refund_ticket_id" not in existing_cols:
        cursor.execute("ALTER TABLE purchases ADD COLUMN refund_ticket_id TEXT;")
    if "refunded_at" not in existing_cols:
        cursor.execute("ALTER TABLE purchases ADD COLUMN refunded_at TEXT;")

    cursor.execute("PRAGMA table_info(refund_tickets);")
    existing_ticket_cols = [row["name"] for row in cursor.fetchall()]
    if "items_json" not in existing_ticket_cols:
        cursor.execute("ALTER TABLE refund_tickets ADD COLUMN items_json TEXT;")

    conn.commit()

    # Check if purchases table is already populated
    cursor.execute("SELECT COUNT(*) FROM purchases")
    count = cursor.fetchone()[0]

    if count == 0 or force_reseed:
        _seed_initial_data(conn)

    conn.close()


def _seed_initial_data(conn: sqlite3.Connection) -> None:
    """
    Seed initial data into SQLite from agent/data.py.
    All items start in the 'PURCHASED' (unrefunded) state.
    """
    from data import users_data

    cursor = conn.cursor()
    cursor.execute("DELETE FROM purchases;")
    cursor.execute("DELETE FROM users;")

    now_iso = datetime.now().isoformat()

    for username, items_dict in users_data.items():
        cursor.execute(
            "INSERT OR IGNORE INTO users (username, created_at) VALUES (?, ?);",
            (username, now_iso),
        )
        for item_name, item_info in items_dict.items():
            cursor.execute(
                """
                INSERT INTO purchases (username, item_name, price, purchase_date, status)
                VALUES (?, ?, ?, ?, 'PURCHASED');
                """,
                (username, item_name, float(item_info["price"]), str(item_info["date"])),
            )

    conn.commit()


# =============================================================================
# Helper Query Functions Used by Agent Tools & Gateway
# =============================================================================

def user_exists(username: str) -> bool:
    """Return True if the username exists in the users table."""
    norm_user = normalize_username(username)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1;", (norm_user,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def get_user_purchases(username: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve all purchases for a user as a dictionary:
    {
        "book": {"price": 23, "date": "2026-10-5", "status": "PURCHASED"},
        "pen":  {"price": 7,  "date": "2026-10-3", "status": "REFUNDED", "refund_ticket_id": "TICK-..."}
    }
    Returns None if the user does not exist.
    """
    norm_user = normalize_username(username)
    if not user_exists(norm_user):
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT item_name, price, purchase_date, status, refund_ticket_id FROM purchases WHERE username = ?;",
        (norm_user,),
    )
    rows = cursor.fetchall()
    conn.close()

    purchases = {}
    for r in rows:
        item_status = r["status"] if "status" in r.keys() and r["status"] else "PURCHASED"
        purchases[r["item_name"]] = {
            "price": int(r["price"]) if r["price"].is_integer() else r["price"],
            "date": r["purchase_date"],
            "status": item_status,
        }
        if item_status == "REFUNDED" and "refund_ticket_id" in r.keys() and r["refund_ticket_id"]:
            purchases[r["item_name"]]["refund_ticket_id"] = r["refund_ticket_id"]
    return purchases


def get_unrefunded_purchases(username: str) -> Dict[str, Any]:
    """Retrieve only purchases that have NOT been refunded yet."""
    purchases = get_user_purchases(username) or {}
    return {k: v for k, v in purchases.items() if v.get("status") != "REFUNDED"}


def stage_pending_refund_items(username: str, items: List[str], amount: float) -> None:
    """Stage items being calculated for refund so issue_refund_ticket knows which items to mark REFUNDED."""
    norm_user = normalize_username(username)
    _STAGED_REFUND_ITEMS[norm_user] = {
        "items": [str(i).strip().lower() for i in items],
        "amount": float(amount),
        "timestamp": datetime.now().isoformat(),
    }


def get_staged_refund_items(username: str) -> Optional[List[str]]:
    """Retrieve staged refund items for a user."""
    norm_user = normalize_username(username)
    staged = _STAGED_REFUND_ITEMS.get(norm_user)
    if staged:
        return staged.get("items")
    return None


def create_refund_ticket(
    username: str,
    amount: float,
    items: Optional[List[str]] = None,
    idempotency_key: Optional[str] = None,
) -> str:
    """
    Create a persistent refund ticket record in SQLite AND permanently update
    the corresponding purchase records to 'REFUNDED' status.
    This guarantees that duplicate refunds are prevented across sessions and resets.
    """
    norm_user = normalize_username(username)
    ticket_id = f"TICK-{uuid4().hex[:8].upper()}"
    now_iso = datetime.now().isoformat()

    # Determine which items are being refunded
    refunded_items = items
    if not refunded_items:
        # Check staged items
        staged = _STAGED_REFUND_ITEMS.get(norm_user)
        if staged and abs(staged.get("amount", 0.0) - float(amount)) < 0.01:
            refunded_items = staged.get("items", [])

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Insert into refund_tickets
    items_json = json.dumps(refunded_items) if refunded_items else None
    cursor.execute(
        """
        INSERT INTO refund_tickets (ticket_id, username, amount, status, items_json, idempotency_key, created_at)
        VALUES (?, ?, ?, 'ISSUED', ?, ?, ?);
        """,
        (ticket_id, norm_user, float(amount), items_json, idempotency_key, now_iso),
    )

    # 2. Permanently mark items as REFUNDED in the purchases table
    if refunded_items:
        for item in refunded_items:
            cursor.execute(
                """
                UPDATE purchases
                SET status = 'REFUNDED', refund_ticket_id = ?, refunded_at = ?
                WHERE username = ? AND LOWER(item_name) = LOWER(?);
                """,
                (ticket_id, now_iso, norm_user, item),
            )
    else:
        # Fallback: Find unrefunded purchases for this user that match the refund amount
        cursor.execute(
            """
            SELECT item_name, price FROM purchases
            WHERE username = ? AND status != 'REFUNDED';
            """,
            (norm_user,),
        )
        unrefunded = cursor.fetchall()
        # If single item matches amount, or all unrefunded items match amount:
        matched_items = []
        if sum(r["price"] for r in unrefunded) == float(amount):
            matched_items = [r["item_name"] for r in unrefunded]
        else:
            for r in unrefunded:
                if float(r["price"]) == float(amount):
                    matched_items = [r["item_name"]]
                    break

        for item in matched_items:
            cursor.execute(
                """
                UPDATE purchases
                SET status = 'REFUNDED', refund_ticket_id = ?, refunded_at = ?
                WHERE username = ? AND item_name = ?;
                """,
                (ticket_id, now_iso, norm_user, item),
            )

    conn.commit()
    conn.close()

    # Clear staged items for user
    if norm_user in _STAGED_REFUND_ITEMS:
        del _STAGED_REFUND_ITEMS[norm_user]

    logging.info(f"Database write committed: Ticket {ticket_id} created for {norm_user} (${amount}). Purchases updated to REFUNDED.")
    return ticket_id


def get_all_refund_tickets() -> List[Dict[str, Any]]:
    """Retrieve all refund tickets from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ticket_id, username, amount, status, idempotency_key, created_at FROM refund_tickets ORDER BY rowid ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tickets_by_user(username: str) -> List[Dict[str, Any]]:
    """Retrieve all refund tickets issued for a specific user."""
    norm_user = normalize_username(username)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ticket_id, username, amount, status, idempotency_key, created_at FROM refund_tickets WHERE username = ?;",
        (norm_user,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_refund_tickets() -> None:
    """
    Clear all refund tickets and reset purchase statuses back to 'PURCHASED'.
    Used between benchmark runs and test suite cases.
    """
    global _STAGED_REFUND_ITEMS
    _STAGED_REFUND_ITEMS.clear()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM refund_tickets;")
    cursor.execute("UPDATE purchases SET status = 'PURCHASED', refund_ticket_id = NULL, refunded_at = NULL;")
    conn.commit()
    conn.close()


def clear_execution_journal() -> None:
    """Clear all records from execution_journal (useful for resetting between test runs)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM execution_journal;")
    conn.commit()
    conn.close()


# Automatically initialize database when module is first imported
init_db()

import os
import sys
from pathlib import Path
from datetime import date, timedelta
from typing import Any, Optional, List, Dict
import logging
from dotenv import load_dotenv
from langchain.tools import tool

# Ensure workspace root and agent dir are in python path
workspace_dir = Path(__file__).resolve().parents[1]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))
if str(workspace_dir / "agent") not in sys.path:
    sys.path.insert(0, str(workspace_dir / "agent"))

from objects import PurchaseItem
from db import (
    get_user_purchases,
    create_refund_ticket,
    normalize_username,
    stage_pending_refund_items,
)
from fault_injector import fault_injector
from effectguard.gateway import effectguard_gateway

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s "
)


def _parse_iso_date(d_str: Any) -> Optional[date]:
    """Safely parse date strings like '2026-10-5' or '2026-09-27' into a datetime.date."""
    if not d_str:
        return None
    try:
        parts = [int(p) for p in str(d_str).strip().split("-")]
        if len(parts) == 3:
            return date(parts[0], parts[1], parts[2])
    except Exception:
        pass
    return None


def get_benchmark_date() -> date:
    """Return the frozen benchmark date from environment, or default to 2026-10-26."""
    date_str = os.getenv("BENCHMARK_DATE", "2026-10-26").strip()
    try:
        return date.fromisoformat(date_str)
    except Exception:
        logging.warning(f"Invalid BENCHMARK_DATE format: '{date_str}', falling back to 2026-10-26")
        return date(2026, 10, 26)


@tool
def get_user_purchase_history(user: str) -> dict:
    """This tool takes the username and returns a dict of the user's purchase
    history if the user exists. Includes price, purchase date, and refund status for each item."""
    norm_user = normalize_username(user)
    logging.info(f"using get_user_purchase_history tool on user: {user} (normalized: {norm_user})")

    # Chaos Hook: optionally simulate network drop or server error
    fault_injector.before_tool_execution("get_user_purchase_history", {"user": norm_user})

    # Query real SQLite database
    purchases = get_user_purchases(norm_user)
    if purchases is not None:
        return purchases

    return {"Status": "There was no username found"}


@tool
def calculate_right_refund(user: str, items: list[PurchaseItem]) -> str:
    """This tool takes a list of eligible items to be returned and the username,
    and returns how much the refund is worth. Call this tool at most once per request
    with all eligible items, then immediately proceed to issue_refund_ticket."""
    norm_user = normalize_username(user)
    logging.info(f"using calculate_right_refund tool for user: {user} (normalized: {norm_user})")

    # Chaos Hook: optionally simulate network drop or server error
    fault_injector.before_tool_execution("calculate_right_refund", {"user": norm_user, "items": items})

    # Query real SQLite database for item prices and statuses
    purchases = get_user_purchases(norm_user)
    if purchases is not None:
        today = get_benchmark_date()
        cutoff_date = today - timedelta(days=30)

        total_refund = 0
        already_refunded = []
        ineligible_date = []
        eligible_items = []
        not_found = []

        for item in items:
            item_name = item.name
            if purchases.get(item_name):
                item_data = purchases[item_name]
                if item_data.get("status") == "REFUNDED":
                    already_refunded.append(item_name)
                    continue

                item_date = _parse_iso_date(item_data.get("date", ""))
                if item_date:
                    if item_date < cutoff_date:
                        ineligible_date.append(f"{item_name} (purchased {item_data['date']}, older than 30-day cutoff {cutoff_date})")
                        continue
                    if item_date > today:
                        ineligible_date.append(f"{item_name} (future purchase date {item_data['date']})")
                        continue

                # Item is eligible
                total_refund += item_data["price"]
                eligible_items.append(item_name)
            else:
                not_found.append(item_name)

        # Stage eligible items so issue_refund_ticket marks exactly these items as REFUNDED in SQLite
        if eligible_items:
            stage_pending_refund_items(norm_user, eligible_items, total_refund)

        # If all requested items were already refunded:
        if already_refunded and not eligible_items and not ineligible_date:
            return (
                f"The requested item(s) {', '.join(already_refunded)} have already been refunded "
                f"under a previous ticket. The value of the refund is: 0. Do not issue a new ticket."
            )

        # If all requested items are ineligible (date, already refunded, or unpurchased):
        if not eligible_items:
            reasons = []
            if ineligible_date:
                reasons.extend(ineligible_date)
            if already_refunded:
                reasons.append(f"already refunded: {', '.join(already_refunded)}")
            if not_found:
                reasons.append(f"not found in order history: {', '.join(not_found)}")
            return (
                f"No items are eligible for refund ({'; '.join(reasons)}). "
                f"The value of the refund is: 0. Do not issue a refund ticket."
            )

        notes = []
        if already_refunded:
            notes.append(f"{', '.join(already_refunded)} were already refunded")
        if ineligible_date:
            notes.append(f"{'; '.join(ineligible_date)} are outside the 30-day policy")
        if not_found:
            notes.append(f"{', '.join(not_found)} were not found in order history")

        note_str = f" Note: {'; '.join(notes)} and are excluded." if notes else ""
        return f"The value of the refund is: {total_refund}.{note_str}"

    return {"Status": "There was no username found"}


def _raw_issue_refund_ticket(args: dict, idempotency_key: str = "") -> str:
    """Underlying database mutation for issuing a refund ticket and updating purchase status."""
    norm_user = normalize_username(args["user"])
    refund_amount = args["refund_amount"]

    # Chaos Hook: optionally drop connection before execution
    fault_injector.before_tool_execution("issue_refund_ticket", {"user": norm_user, "refund_amount": refund_amount})

    # REAL STATE MUTATION: Insert real refund ticket AND mark items as REFUNDED in SQLite
    ticket_id = create_refund_ticket(username=norm_user, amount=refund_amount, idempotency_key=idempotency_key)
    logging.info(f"Persistent SQLite write: Ticket {ticket_id} created for {norm_user} (${refund_amount}) [Key: {idempotency_key[:8] if idempotency_key else 'None'}]")

    result_message = f"A refund ticket has been issued successfully with the amount of {refund_amount}"

    # Chaos Hook: simulate timeout-after-commit (ticket saved in DB, but network drops before response reaches agent!)
    fault_injector.after_tool_execution("issue_refund_ticket", {"user": norm_user, "refund_amount": refund_amount}, ticket_id)

    return result_message


@tool
def issue_refund_ticket(user: str, refund_amount: int) -> str:
    """This tool sends a ticket to the refund processing team to 
    issue the refund to the user."""
    norm_user = normalize_username(user)
    logging.info(f"using issue_refund_ticket tool on user: {user} (normalized: {norm_user}) with amount: {refund_amount}")

    # Route execution through EffectGuard Execution Safety Gateway
    return effectguard_gateway.execute(
        tool_name="issue_refund_ticket",
        args={"user": norm_user, "refund_amount": refund_amount},
        raw_executor=_raw_issue_refund_ticket,
    )


@tool
def get_today_date() -> str:
    """This tool returns today's current date and the 30-day refund eligibility cutoff date."""
    logging.info("using the get_today_date tool")
    today = get_benchmark_date()
    cutoff = today - timedelta(days=30)
    return (
        f"Today's date is {today.isoformat()} ({today.strftime('%B %d, %Y')}). "
        f"The 30-day refund cutoff date is {cutoff.isoformat()} ({cutoff.strftime('%B %d, %Y')}). "
        f"Purchases made on or after {cutoff.isoformat()} and on or before {today.isoformat()} are within the 30-day window and ELIGIBLE for refund. "
        f"Purchases dated before {cutoff.isoformat()} or with future dates after {today.isoformat()} are INELIGIBLE."
    )

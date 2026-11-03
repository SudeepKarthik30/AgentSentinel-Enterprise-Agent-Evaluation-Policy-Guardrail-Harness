"""
Policy Engine for EffectGuard.

Loads declarative rules from policy.yaml and validates tool preconditions
in deterministic code before any tool executes.

This guarantees that an adversarial prompt or hallucinated LLM decision cannot
violate corporate invariants (e.g. issuing a ticket to a non-existent user,
issuing duplicate refunds for already-refunded items, or issuing a negative refund).
"""

import os
from pathlib import Path
from typing import Dict, Any, Tuple
import yaml
import sys

# Ensure agent directory is importable for database checks
ROOT_DIR = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT_DIR / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from db import user_exists, normalize_username, get_unrefunded_purchases

POLICY_PATH = Path(__file__).resolve().parent / "policy.yaml"


class PolicyEngine:
    """
    Evaluates tool preconditions using deterministic Python logic
    based on declarative rules in policy.yaml.
    """

    def __init__(self, config_path: Path = POLICY_PATH):
        self.config_path = config_path
        self.config: Dict[str, Any] = self._load_policy()

    def _load_policy(self) -> Dict[str, Any]:
        """Load YAML configuration safely."""
        if not self.config_path.exists():
            return {"tools": {}}
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"tools": {}}

    def reload(self) -> None:
        """Reload configuration from disk."""
        self.config = self._load_policy()

    def get_effect_class(self, tool_name: str) -> str:
        """Return effect class ('read_only' or 'irreversible') for a tool."""
        tool_cfg = self.config.get("tools", {}).get(tool_name, {})
        return tool_cfg.get("effect_class", "read_only")

    def validate_preconditions(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate all preconditions defined in policy.yaml for the specified tool.
        Returns:
            (allowed: bool, reason: str)
        """
        tool_cfg = self.config.get("tools", {}).get(tool_name, {})
        preconditions = tool_cfg.get("preconditions", [])

        user = normalize_username(str(args.get("user", "")).strip())
        amount_raw = args.get("refund_amount", None)

        for rule in preconditions:
            # 1. User Existence Invariant
            if rule == "user_exists":
                if not user:
                    return False, "Policy Invariant Failed: Missing username in tool parameters."
                if not user_exists(user):
                    return False, f"Policy Invariant Failed: User '{user}' does not exist in the database."

            # 2. Positive Amount Invariant
            elif rule == "positive_amount":
                if amount_raw is None:
                    return False, "Policy Invariant Failed: Missing refund_amount parameter."
                try:
                    amount = float(amount_raw)
                    if amount <= 0:
                        return False, f"Policy Invariant Failed: Refund amount must be strictly greater than $0 (received ${amount})."
                except (ValueError, TypeError):
                    return False, f"Policy Invariant Failed: Invalid numeric amount '{amount_raw}'."

            # 3. Maximum Safety Ceiling Invariant
            elif rule == "within_safety_ceiling":
                ceiling = tool_cfg.get("max_amount_ceiling", 500)
                try:
                    amount = float(amount_raw)
                    if amount > ceiling:
                        return False, f"Policy Invariant Failed: Requested amount ${amount} exceeds safety ceiling of ${ceiling}."
                except (ValueError, TypeError):
                    pass

            # 4. Unrefunded Purchases Invariant (Prevents duplicate refunds on already-refunded items)
            elif rule == "has_unrefunded_purchases":
                unrefunded = get_unrefunded_purchases(user)
                if not unrefunded:
                    return False, f"Policy Invariant Failed: User '{user}' has no unrefunded items in database. Duplicate refund prevented."

                # Compute maximum eligible balance strictly within the 30-day window
                date_str = os.getenv("BENCHMARK_DATE", "2026-10-26").strip()
                try:
                    from datetime import date, timedelta
                    bench_today = date.fromisoformat(date_str)
                    cutoff = bench_today - timedelta(days=30)
                    eligible_purchases = {}
                    for item, p_data in unrefunded.items():
                        parts = [int(p) for p in str(p_data.get("date", "")).split("-")]
                        if len(parts) == 3:
                            p_date = date(parts[0], parts[1], parts[2])
                            if cutoff <= p_date <= bench_today:
                                eligible_purchases[item] = p_data
                    max_eligible = sum(v["price"] for v in eligible_purchases.values())
                except Exception:
                    max_eligible = sum(v["price"] for v in unrefunded.values())

                try:
                    amount = float(amount_raw)
                    if amount > max_eligible:
                        return False, f"Policy Invariant Failed: Requested refund of ${amount} exceeds remaining unrefunded eligible balance of ${max_eligible}."
                except (ValueError, TypeError):
                    pass

        return True, "All preconditions successfully verified by PolicyEngine."


# Global singleton instance
policy_engine = PolicyEngine()

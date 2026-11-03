"""
EffectGuard: Execution Safety Gateway for Tool-Calling LLM Agents.

Provides:
- Policy-as-Code (YAML declarative preconditions)
- Deterministic SHA-256 Idempotency Keys
- Write-Ahead Logging (WAL) & Execution Journaling
- Verify-Before-Retry recovery under distributed network faults
"""

from .policy_engine import policy_engine
from .gateway import effectguard_gateway
from .claim_auditor import claim_auditor

__all__ = ["policy_engine", "effectguard_gateway", "claim_auditor"]

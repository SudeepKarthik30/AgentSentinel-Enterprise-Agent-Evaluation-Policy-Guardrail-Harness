"""
Data schemas and structured output models for AgentSentinel.
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field


class answer(BaseModel):
    """Structured response format returned by the customer support agent."""

    answer: str = Field(
        description="The customer-facing natural language response to the user's inquiry."
    )
    conversation: bool = Field(
        description="Whether the multi-turn conversation should continue. "
        "Set to False once a final refund decision or inquiry answer has been delivered. "
        "Set to True if more clarification is needed from the customer.",
        default=True,
    )
    claimed_effects: List[Dict[str, Any]] = Field(
        description="List of real-world state mutations the agent claims it successfully performed. "
        "For example, if a ticket was issued: [{'action': 'issue_refund_ticket', 'user': 'sarah_m', 'amount': 45}]. "
        "If no refund was issued (e.g. inquiry or denial), return an empty list [].",
        default_factory=list,
    )


# Backward-compatibility alias
Answer = answer


class PurchaseItem(BaseModel):
    """Represents a single purchased item requested for refund."""

    name: str = Field(description="Name of the purchased item")

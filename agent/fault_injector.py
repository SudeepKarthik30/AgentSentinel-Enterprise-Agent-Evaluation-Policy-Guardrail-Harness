"""
Chaos Fault Injector for AgentSentinel.

This module simulates real-world distributed system failures (network drops,
timeouts, and 504 Gateway Timeouts) during tool execution.

Why is this needed?
In production, network requests fail. If an agent tries to issue a refund and the
connection drops right after the database commits, a naive agent will retry the
tool call. Without idempotency guards, this results in duplicate refunds!

This module lets us test that failure mode deterministically.
"""

import os
import random
import logging
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


class FaultInjector:
    """
    Lightweight Chaos Engine that randomly intercepts tool calls to simulate failures.
    """

    def __init__(self):
        # Read default fault rate from environment (0.0 means no faults injected)
        rate_str = os.getenv("FAULT_RATE", "0.0")
        try:
            self.fault_rate: float = float(rate_str)
        except ValueError:
            self.fault_rate = 0.0

        # Mode can be 'random', 'timeout_after_commit', 'drop_before_exec', or 'server_error'
        self.fault_mode: str = os.getenv("FAULT_MODE", "random")
        self.enabled: bool = self.fault_rate > 0.0

        # Telemetry: count total faults injected
        self.faults_injected_count: int = 0

    def enable(self, rate: float = 0.20, mode: str = "random") -> None:
        """Enable chaos fault injection with a specific probability rate."""
        self.fault_rate = max(0.0, min(1.0, rate))
        self.fault_mode = mode
        self.enabled = True
        logging.info(f"Chaos Fault Injector ENABLED with rate={self.fault_rate} and mode='{self.fault_mode}'")

    def disable(self) -> None:
        """Disable chaos fault injection completely."""
        self.enabled = False
        self.fault_rate = 0.0
        logging.info("Chaos Fault Injector DISABLED")

    def should_fault(self) -> bool:
        """Roll random dice against the configured fault rate."""
        if not self.enabled or self.fault_rate <= 0.0:
            return False
        return random.random() < self.fault_rate

    def before_tool_execution(self, tool_name: str, args: Dict[str, Any]) -> None:
        """
        Called right before a tool executes.
        Can simulate connection drops (504) or server crashes (500) prior to execution.
        """
        if not self.should_fault():
            return

        mode = self._resolve_mode()

        if mode == "drop_before_exec":
            self.faults_injected_count += 1
            logging.warning(f"CHAOS FAULT: Dropping call to '{tool_name}' before execution (504 Gateway Timeout)")
            raise TimeoutError(f"Network timeout: 504 Gateway Timeout while calling '{tool_name}'")

        elif mode == "server_error":
            self.faults_injected_count += 1
            logging.warning(f"CHAOS FAULT: Injecting 500 Internal Server Error into '{tool_name}'")
            raise RuntimeError(f"Internal Server Error: 500 when invoking tool '{tool_name}'")

    def after_tool_execution(self, tool_name: str, args: Dict[str, Any], result: Any) -> None:
        """
        Called right AFTER a tool executes successfully.
        Specifically simulates 'Timeout-After-Commit': the database wrote the refund ticket,
        but the network connection dropped before the confirmation reached the agent!
        """
        if not self.should_fault():
            return

        mode = self._resolve_mode()

        # Timeout-after-commit is the critical vulnerability for irreversible state mutations
        if tool_name == "issue_refund_ticket" and mode in ("timeout_after_commit", "random"):
            self.faults_injected_count += 1
            logging.warning(f"CHAOS FAULT: Injected Timeout-After-Commit on '{tool_name}'. State committed, but client disconnected!")
            raise TimeoutError("Connection dropped: 504 Timeout occurred after server commit")

    def _resolve_mode(self) -> str:
        """Pick mode, selecting randomly if mode is 'random'."""
        if self.fault_mode == "random":
            return random.choice(["drop_before_exec", "timeout_after_commit", "server_error"])
        return self.fault_mode


# Global singleton instance for easy import across agent tools
fault_injector = FaultInjector()

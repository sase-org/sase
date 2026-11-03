"""Archived gate-turn pending-marker name for kill-path readers.

In-agent pending gates stage and return. This module no longer writes a
pending marker or kills the runner.
"""

from sase.agent.pending_handoff import GATE_PENDING_MARKER

__all__ = ["GATE_PENDING_MARKER"]

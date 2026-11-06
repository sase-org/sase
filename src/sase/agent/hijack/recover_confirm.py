"""Post-spawn confirmation: identity, claim, inheritance, settlement."""

from __future__ import annotations

from sase.agent.hijack._recover_confirm_flow import confirm_and_settle
from sase.agent.hijack._recover_confirm_rollback import successor_holds_claim

__all__ = ["confirm_and_settle", "successor_holds_claim"]

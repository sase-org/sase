"""Result types shared by the hijack preview adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecoveryAction:
    """One action row returned by the Rust recovery preview policy."""

    action: str
    available: bool
    reason: str | None
    label: str
    detail: str
    target: str | None


@dataclass(frozen=True)
class RecoveryPreview:
    """Stable adapter result for CLI, TUI, and recovery transaction callers."""

    hijack_id: str
    revision: int
    header: Mapping[str, Any]
    default_action: str | None
    actions: tuple[RecoveryAction, ...]
    state: str
    _record: Mapping[str, Any] = field(repr=False, compare=False)
    _artifacts_dir: str = field(repr=False, compare=False)

    def action(self, name: str) -> RecoveryAction | None:
        """Return the preview row for *name*, if present."""
        return next((item for item in self.actions if item.action == name), None)

    def to_dict(self) -> dict[str, Any]:
        """Return the public wire payload without the local ledger snapshot."""
        return {
            "hijack_id": self.hijack_id,
            "revision": self.revision,
            "header": dict(self.header),
            "default_action": self.default_action,
            "actions": [
                {
                    "action": action.action,
                    "available": action.available,
                    "reason": action.reason,
                    "label": action.label,
                    "detail": action.detail,
                    "target": action.target,
                }
                for action in self.actions
            ],
        }


@dataclass(frozen=True)
class HijackContinuationPrompt:
    """Prepared prompt and the side-effect-free context budget decision."""

    prompt: str
    model_target: str
    context_mode: str
    transcript_path: str | None
    expanded_prompt_bytes: int
    budget_decision: Mapping[str, Any]


class HijackRecoveryRefusal(RuntimeError):
    """A typed, user-actionable reason a recovery prompt cannot be prepared."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

"""Effective default-effort snapshots and launch precedence resolution."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.core.rust import require_rust_binding
from sase.xprompt.effort import is_valid_effort

if TYPE_CHECKING:
    from sase.xprompt.directives import PromptDirectives

    from .effort_override import TemporaryEffortOverride


@dataclass(frozen=True)
class EffectiveDefaultEffortSnapshot:
    """Configured and temporary values captured for one launch/UI snapshot."""

    configured_effort: str | None
    temporary_override: TemporaryEffortOverride | None
    captured_at: float

    def active_override(
        self, now: float | None = None
    ) -> TemporaryEffortOverride | None:
        """Return the captured override while it remains locally active."""
        override = self.temporary_override
        current = self.captured_at if now is None else now
        if override is not None and override.is_active(current):
            return override
        return None

    def effective_effort(self, now: float | None = None) -> str | None:
        """Return temporary effort when active, else the configured value."""
        override = self.active_override(now)
        return override.effort if override is not None else self.configured_effort


def build_effective_default_effort_snapshot(
    configured_effort: str | None,
    temporary_override: TemporaryEffortOverride | None,
    *,
    now: float | None = None,
) -> EffectiveDefaultEffortSnapshot:
    """Capture configured and active temporary launch defaults together."""
    captured_at = time.time() if now is None else now
    return EffectiveDefaultEffortSnapshot(
        configured_effort=configured_effort,
        temporary_override=temporary_override,
        captured_at=captured_at,
    )


def resolve_effective_effort_from_snapshot(
    directives: PromptDirectives,
    alias_effort: str | None,
    snapshot: EffectiveDefaultEffortSnapshot,
) -> tuple[str | None, bool]:
    """Resolve launch effort using explicit, alias, temporary, config order.

    An explicit per-branch ``%effort``/``@effort`` wins and is marked explicit.
    Alias effort, a machine-wide temporary override, and configured effort are
    all best-effort defaults. With none of those set, the provider keeps its
    own default.
    """
    override = snapshot.active_override()
    binding = require_rust_binding("resolve_effective_effort")
    payload: Any = binding(
        directives.reasoning_effort,
        alias_effort,
        override.effort if override is not None else None,
        snapshot.configured_effort,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("invalid effective-effort resolution from Rust")
    level = payload.get("level")
    explicit = payload.get("explicit")
    if level is not None and (not isinstance(level, str) or not is_valid_effort(level)):
        raise RuntimeError("Rust returned an invalid effective-effort level")
    if not isinstance(explicit, bool):
        raise RuntimeError("Rust returned an invalid effective-effort explicit flag")
    return level, explicit


__all__ = [
    "EffectiveDefaultEffortSnapshot",
    "build_effective_default_effort_snapshot",
    "resolve_effective_effort_from_snapshot",
]

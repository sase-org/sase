"""Immutable surface-token types for ACE auto-refresh."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SurfaceToken:
    """Immutable metadata token for one ACE refresh surface.

    ``part_kinds`` is parallel to ``parts`` and does not participate in
    equality: a heartbeat rewrite of an unconsumed file still changes
    ``parts``, while consumers filter by kind before deciding to reload.
    """

    surface: str
    parts: tuple[tuple[str, bool, int | None, int | None], ...]
    indeterminate: bool = False
    part_kinds: tuple[str, ...] = ()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SurfaceToken):
            return NotImplemented
        return (
            self.surface == other.surface
            and self.parts == other.parts
            and self.indeterminate == other.indeterminate
        )

    def __hash__(self) -> int:
        return hash((self.surface, self.parts, self.indeterminate))


@dataclass(frozen=True)
class SurfaceTokenSnapshot:
    """One probe of every ACE refresh surface."""

    agents: SurfaceToken
    axe: SurfaceToken
    notifications: SurfaceToken
    patches: SurfaceToken
    procs: SurfaceToken
    tool_runs: SurfaceToken | None = None
    runner_capacity: SurfaceToken | None = None

    def token_for(self, surface: str) -> SurfaceToken:
        """Return the token for *surface*."""
        try:
            token = getattr(self, surface)
        except AttributeError as exc:
            raise KeyError(surface) from exc
        if not isinstance(token, SurfaceToken):
            raise KeyError(surface)
        return token


@dataclass(frozen=True)
class SurfaceTokenRoots:
    """Filesystem roots a token probe may inspect."""

    projects_root: Path
    axe_root: Path
    notifications_path: Path
    procs_path: Path
    beads_dir: Path | None = None
    agent_index_path: Path | None = None
    runner_limit_override_path: Path | None = None
    agent_hold_store_path: Path | None = None
    runner_slot_token_path: Path | None = None
    service_dir: Path | None = None
    service_state_path: Path | None = None
    service_status_path: Path | None = None
    tool_run_store_path: Path | None = None
    tool_run_wal_path: Path | None = None


__all__ = [
    "SurfaceToken",
    "SurfaceTokenRoots",
    "SurfaceTokenSnapshot",
]

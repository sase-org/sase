"""Surface-token helpers for TUI auto-refresh."""

from __future__ import annotations

from ._sdd_paths import cached_sdd_beads_dir
from ._surface_tokens import (
    SurfaceToken,
    SurfaceTokenRoots,
    SurfaceTokenSnapshot,
    live_surface_token_roots,
    probe_surface_tokens,
    surface_token_drifted,
)


class EventAutoRefreshTokenMixin:
    """Mixin for refresh-token probing and drift bookkeeping."""

    def _probe_surface_tokens(self) -> SurfaceTokenSnapshot:
        """Collect metadata-only tokens for every ACE refresh surface."""
        roots: SurfaceTokenRoots = live_surface_token_roots(
            beads_dir=cached_sdd_beads_dir(self)
        )
        return probe_surface_tokens(roots)

    def _accept_surface_token(
        self,
        surface: str,
        snapshot: SurfaceTokenSnapshot | None,
    ) -> None:
        """Record *surface*'s probed token after a successful load."""
        if snapshot is None:
            return
        token = snapshot.token_for(surface)
        if token.indeterminate:
            return
        tokens: dict[str, object] | None = getattr(
            self,
            "_last_completed_surface_tokens",
            None,
        )
        if tokens is None:
            tokens = {}
            self._last_completed_surface_tokens = tokens
        tokens[surface] = token

    def _surface_token_drifted(
        self,
        snapshot: SurfaceTokenSnapshot | None,
        surface: str,
    ) -> bool:
        if snapshot is None:
            return True
        last = getattr(self, "_last_completed_surface_tokens", {}).get(surface)
        last_token = last if isinstance(last, SurfaceToken) else None
        drifted = surface_token_drifted(snapshot.token_for(surface), last_token)
        if drifted and surface == "agents":
            bump_capacity = getattr(self, "_bump_agents_capacity_generation", None)
            if callable(bump_capacity):
                bump_capacity()
        return drifted

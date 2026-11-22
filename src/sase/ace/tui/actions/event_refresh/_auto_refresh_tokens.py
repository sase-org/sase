"""Surface-token helpers for TUI auto-refresh."""

from __future__ import annotations

from ._sdd_paths import cached_sdd_beads_dir
from ._surface_tokens import (
    SurfaceToken,
    SurfaceTokenRoots,
    SurfaceTokenSnapshot,
    agents_token_reload_kind,
    axe_token_changed_kinds,
    axe_token_consumer_drifted,
    live_surface_token_roots,
    probe_surface_tokens,
    surface_token_changed_kinds,
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

    def _accept_startup_hold_surface_tokens(
        self,
        snapshot: SurfaceTokenSnapshot | None,
    ) -> None:
        """Seed the post-release baseline from a hold-tick probe.

        Hold ticks must not reload, but they still probe so the first
        tick after release can detect genuine drift instead of treating
        every surface as new. Agents is omitted: its baseline is the
        token probed before the startup Agents load reads disk, accepted
        when that load succeeds, so a hold-tick accept cannot hide
        drift that arrived while the load was in flight.
        """
        if snapshot is None:
            return
        for surface in (
            "axe",
            "notifications",
            "patches",
            "procs",
            "tool_runs",
        ):
            try:
                self._accept_surface_token(surface, snapshot)
            except KeyError:
                continue

    def _surface_token_drifted(
        self,
        snapshot: SurfaceTokenSnapshot | None,
        surface: str,
    ) -> bool:
        drifted = self._surface_token_consumer_drifted(snapshot, surface)
        if surface == "agents" and drifted:
            bump_capacity = getattr(self, "_bump_agents_capacity_generation", None)
            if callable(bump_capacity):
                bump_capacity()
        return drifted

    def _surface_token_consumer_drifted(
        self,
        snapshot: SurfaceTokenSnapshot | None,
        surface: str,
    ) -> bool:
        """Compare a consumer projection without scheduling side effects."""
        if snapshot is None:
            return True
        last = getattr(self, "_last_completed_surface_tokens", {}).get(surface)
        last_token = last if isinstance(last, SurfaceToken) else None
        if surface == "axe":
            return axe_token_consumer_drifted(
                snapshot.token_for(surface),
                last_token,
                consume_details=self._axe_consumes_detail_parts(),
            )
        drifted = surface_token_drifted(snapshot.token_for(surface), last_token)
        if surface == "agents":
            kind = self._agents_token_reload_kind(snapshot)
            if kind == "skip":
                return False
        return drifted

    def _axe_consumes_detail_parts(self) -> bool:
        """Services tab (and sanity) consume lumberjack status/metrics/logs."""
        return getattr(self, "current_tab", None) == "services"

    def _last_surface_token(self, surface: str) -> SurfaceToken | None:
        last = getattr(self, "_last_completed_surface_tokens", {}).get(surface)
        return last if isinstance(last, SurfaceToken) else None

    def _surface_token_change_kinds(
        self,
        snapshot: SurfaceTokenSnapshot | None,
        surface: str,
        *,
        consumed_only: bool = True,
    ) -> tuple[str, ...]:
        """Return bounded changed-part labels for trace attribution."""
        if snapshot is None:
            return ("unknown",)
        try:
            current = snapshot.token_for(surface)
        except KeyError:
            return ("unknown",)
        previous = self._last_surface_token(surface)
        if surface == "axe" and consumed_only:
            return axe_token_changed_kinds(
                current,
                previous,
                consume_details=self._axe_consumes_detail_parts(),
            )
        return surface_token_changed_kinds(current, previous)

    def _surface_token_raw_drifted(
        self,
        snapshot: SurfaceTokenSnapshot | None,
        surface: str,
    ) -> bool:
        """Return whether any token part changed, including unconsumed parts."""
        if snapshot is None:
            return True
        try:
            current = snapshot.token_for(surface)
        except KeyError:
            return True
        return surface_token_drifted(current, self._last_surface_token(surface))

    def _agents_token_reload_kind(
        self,
        snapshot: SurfaceTokenSnapshot | None,
    ) -> str:
        if snapshot is None:
            return "load"
        watcher_active = getattr(self, "_watcher_active", None)
        return agents_token_reload_kind(
            snapshot.token_for("agents"),
            self._last_surface_token("agents"),
            watcher_active=bool(watcher_active())
            if callable(watcher_active)
            else False,
        )

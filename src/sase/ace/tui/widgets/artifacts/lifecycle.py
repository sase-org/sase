"""Lazy lifecycle contract shared by Artifacts panes."""


class ArtifactsPaneLifecycle:
    """Lifecycle hooks shared by every mounted Artifacts pane."""

    def _init_artifacts_lifecycle(self) -> None:
        self._artifacts_first_activated = False
        self._artifacts_active = False
        self.first_activation_count = 0
        self.activation_count = 0
        self.deactivation_count = 0
        self.refresh_request_count = 0

    @property
    def artifacts_active(self) -> bool:
        """Whether this pane is active on the visible Artifacts tab."""
        return self._artifacts_active

    def activate(self) -> None:
        """Run first-activation once, then the per-activation hook."""
        if self._artifacts_active:
            return
        if not self._artifacts_first_activated:
            self._artifacts_first_activated = True
            self.first_activation_count += 1
            self.on_first_activate()
        self._artifacts_active = True
        self.activation_count += 1
        self.on_activate()

    def deactivate(self) -> None:
        """Deactivate an active pane without discarding mounted state."""
        if not self._artifacts_active:
            return
        self._artifacts_active = False
        self.deactivation_count += 1
        self.on_deactivate()

    def request_refresh(self) -> None:
        """Ask the active pane to refresh through its non-blocking hook."""
        if not self._artifacts_active:
            return
        self.refresh_request_count += 1
        self.on_refresh()

    def on_first_activate(self) -> None:
        """Schedule one-time collection when a concrete pane needs it."""

    def on_activate(self) -> None:
        """Resume active-only refresh behavior."""

    def on_deactivate(self) -> None:
        """Pause active-only refresh behavior."""

    def on_refresh(self) -> None:
        """Schedule a refresh; implementations must not block the event loop."""


__all__ = ["ArtifactsPaneLifecycle"]

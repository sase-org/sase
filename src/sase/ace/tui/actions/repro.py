"""Agents-tab reproduction capture actions."""

from __future__ import annotations

from typing import Any


class ReproActionsMixin:
    """TUI actions for manual and continuous Agents-tab repro capture."""

    current_tab: str
    _agents_repro_auto_check_enabled: bool

    def action_capture_agents_repro(self) -> None:
        """Write an Agents-tab repro bundle for the running TUI session."""
        if self.current_tab != "agents":
            self.notify("Agents repro capture is only available on Agents")  # type: ignore[attr-defined]
            return

        from ..repro.capture import capture_agents_tab_repro_bundle_to_default_dir

        try:
            bundle_path = capture_agents_tab_repro_bundle_to_default_dir(
                self,
                reason="manual",
                commit_safe=True,
            )
        except Exception as exc:
            self.notify(f"Agents repro capture failed: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        self.notify(f"Agents repro captured: {bundle_path}")  # type: ignore[attr-defined]

    def action_toggle_agents_repro_checks(self) -> None:
        """Toggle continuous Agents-tab invariant checks and auto-capture."""
        if self.current_tab != "agents":
            self.notify("Agents repro checks are only available on Agents")  # type: ignore[attr-defined]
            return

        from ..repro.capture import set_agents_tab_repro_auto_check

        enabled = not bool(getattr(self, "_agents_repro_auto_check_enabled", False))
        set_agents_tab_repro_auto_check(self, enabled=enabled)
        status = "enabled" if enabled else "disabled"
        self.notify(f"Agents repro checks {status}")  # type: ignore[attr-defined]

    def _notify_agents_repro_auto_capture(self, bundle_path: Any) -> None:
        """Surface an auto-capture bundle path without coupling capture to Textual."""
        self.notify(f"Agents repro auto-captured: {bundle_path}", severity="warning")  # type: ignore[attr-defined]

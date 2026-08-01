"""Declared action surface for the placeholder Artifacts Beads pane."""

from __future__ import annotations

from typing import Any


BEADS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "beads_next",
        "beads_prev",
        "beads_view_selected",
        "beads_filters",
        "beads_expand",
        "beads_collapse",
        "beads_cycle_status",
        "beads_edit",
        "beads_add_note",
        "beads_create",
        "beads_close",
        "beads_launch_work",
        "beads_open_bug",
        "beads_open_plan",
        "beads_refresh",
    }
)


class ArtifactsBeadsActionsMixin:
    """Keep all configured Beads actions inert until its pane lands."""

    def _beads_pane(self) -> Any | None:
        try:
            return self.query_one("#artifacts-beads-pane")  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None

    def _placeholder_beads_action(self) -> None:
        self._beads_pane()

    def action_beads_next(self) -> None:
        self._placeholder_beads_action()

    def action_beads_prev(self) -> None:
        self._placeholder_beads_action()

    def action_beads_view_selected(self) -> None:
        self._placeholder_beads_action()

    def action_beads_filters(self) -> None:
        self._placeholder_beads_action()

    def action_beads_expand(self) -> None:
        self._placeholder_beads_action()

    def action_beads_collapse(self) -> None:
        self._placeholder_beads_action()

    def action_beads_cycle_status(self) -> None:
        self._placeholder_beads_action()

    def action_beads_edit(self) -> None:
        self._placeholder_beads_action()

    def action_beads_add_note(self) -> None:
        self._placeholder_beads_action()

    def action_beads_create(self) -> None:
        self._placeholder_beads_action()

    def action_beads_close(self) -> None:
        self._placeholder_beads_action()

    def action_beads_launch_work(self) -> None:
        self._placeholder_beads_action()

    def action_beads_open_bug(self) -> None:
        self._placeholder_beads_action()

    def action_beads_open_plan(self) -> None:
        self._placeholder_beads_action()

    def action_beads_refresh(self) -> None:
        self._placeholder_beads_action()


__all__ = ["ArtifactsBeadsActionsMixin", "BEADS_ARTIFACT_ACTIONS"]

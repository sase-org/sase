"""Freshness recorder tests for ACE refresh surfaces."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.event_refresh import _freshness
from sase.ace.tui.actions.event_refresh._freshness import (
    freshness_label,
    note_surface_refreshed,
    surface_refreshed_age,
)


class _ManualRefreshApp:
    def __init__(self, *, current_tab: str, artifacts_subtab: str = "patches") -> None:
        self.current_tab = current_tab
        self.current_artifacts_subtab = artifacts_subtab
        self._agents_history_reconcile_pending = True
        self.calls: list[str] = []
        self.notifications: list[str] = []

    def _schedule_agents_async_refresh(self, **_: object) -> None:
        self.calls.append("agents")

    def _schedule_agents_fleet_refresh(self, **_: object) -> None:
        self.calls.append("fleet")

    def _schedule_patches_async_refresh(self) -> None:
        self.calls.append("patches")

    def _request_active_artifacts_refresh(self) -> None:
        self.calls.append("artifacts")

    def _schedule_targeted_axe_refresh(self) -> None:
        self.calls.append("targeted_axe")

    def _schedule_axe_async_refresh(self) -> None:
        self.calls.append("axe")

    def notify(self, message: str, **_: object) -> None:
        self.notifications.append(message)


@pytest.mark.parametrize(
    ("age", "label"),
    [
        (None, "—"),
        (0.0, "just now"),
        (4.9, "just now"),
        (5.0, "5s ago"),
        (59.0, "59s ago"),
        (60.0, "1m ago"),
        (3599.0, "59m ago"),
        (3600.0, "1h ago"),
        (86_400.0, "1d ago"),
    ],
)
def test_freshness_label_boundaries(age: float | None, label: str) -> None:
    assert freshness_label(age) == label


def test_unknown_surface_stamp_is_noop() -> None:
    app = SimpleNamespace()

    note_surface_refreshed(app, "unknown", now=12.0)

    assert not hasattr(app, "_surface_refreshed_mono")


def test_surface_refreshed_age_before_and_after_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SimpleNamespace()

    assert surface_refreshed_age(app, "agents") is None

    note_surface_refreshed(app, "agents", now=100.0)
    monkeypatch.setattr(_freshness.time, "monotonic", lambda: 112.5)

    assert surface_refreshed_age(app, "agents") == 12.5


@pytest.mark.parametrize(
    ("current_tab", "artifacts_subtab", "surface"),
    [
        ("agents", "patches", "agents"),
        ("artifacts", "patches", "patches"),
        ("artifacts", "beads", "artifacts"),
        ("axe", "patches", "axe"),
    ],
)
def test_manual_refresh_stamps_requested_surface(
    current_tab: str,
    artifacts_subtab: str,
    surface: str,
) -> None:
    from sase.ace.tui.actions.base import BaseActionsMixin

    app = _ManualRefreshApp(
        current_tab=current_tab,
        artifacts_subtab=artifacts_subtab,
    )

    BaseActionsMixin.action_refresh(app)  # type: ignore[arg-type]

    assert surface_refreshed_age(app, surface) is not None


def test_manual_full_history_refresh_stamps_full_history_surface() -> None:
    from sase.ace.tui.actions.base import BaseActionsMixin

    app = _ManualRefreshApp(current_tab="agents")

    BaseActionsMixin.action_refresh_agents_full_history(app)  # type: ignore[arg-type]

    assert surface_refreshed_age(app, "agents_full_history") is not None

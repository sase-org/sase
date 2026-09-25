"""Tests for the one-shot agent data decks post-update notice marker."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui._agent_decks_notice import (
    has_shown_agent_decks_notice,
    mark_agent_decks_notice_shown,
)


def test_agent_decks_notice_marker_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The marker starts absent and persists once, best-effort."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    assert not has_shown_agent_decks_notice()
    mark_agent_decks_notice_shown()
    assert has_shown_agent_decks_notice()
    # Showing again is a no-op that keeps the marker.
    mark_agent_decks_notice_shown()
    assert has_shown_agent_decks_notice()


def test_agent_decks_toast_shows_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The startup hook notifies once and stays silent afterwards."""
    from sase.ace.tui.actions._startup_loads_maintenance import (
        StartupLoadsMaintenanceMixin,
    )

    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    seen: list[tuple[str, str]] = []

    class _App(StartupLoadsMaintenanceMixin):
        def notify(self, message: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            seen.append((message, kwargs.get("title", "")))

    app = _App()
    app._maybe_show_agent_decks_toast()
    assert len(seen) == 1
    assert "decks" in seen[0][0]
    assert "p view picker" in seen[0][0]
    app._maybe_show_agent_decks_toast()
    assert len(seen) == 1

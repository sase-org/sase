"""Tests for Agents-tab info panel state-update paths."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from ._agent_info_panel_helpers import (
    AgentInfoPanel,
    collect_text,
    stable_state_kwargs,
)


def test_update_state_renders_supplied_sase_agent_count_unchanged() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(
            **stable_state_kwargs(
                sase_agent_count=4,
                running=3,
                read=3,
            )
        )  # type: ignore[arg-type]

    plain = collect_text(panel)

    assert plain.startswith("4  2.0/10.0 [3 running · 3 done]")


def test_update_countdown_only_passes_layout_false() -> None:
    """Pure countdown refreshes should request a no-layout repaint."""
    panel = AgentInfoPanel()
    panel._countdown = 5
    panel._interval = 5

    calls: list[dict[str, object]] = []

    def fake_update(text: Text, **kwargs: object) -> None:
        calls.append({"text": text, **kwargs})

    with patch.object(panel, "update", side_effect=fake_update):
        panel.update_countdown_only(4, 5)

    assert len(calls) == 1
    assert calls[0]["layout"] is False
    assert "4s" in calls[0]["text"].plain  # type: ignore[union-attr]


def test_update_countdown_only_returns_early_when_unchanged() -> None:
    """No update is emitted when the countdown text would not change."""
    panel = AgentInfoPanel()
    panel._countdown = 3
    panel._interval = 5

    with patch.object(panel, "update") as mock_update:
        panel.update_countdown_only(3, 5)

    mock_update.assert_not_called()


def test_update_state_routes_countdown_only_to_cheap_path() -> None:
    """Stable-state cache short-circuits to ``update_countdown_only``."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(countdown=5))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**stable_state_kwargs(countdown=4))  # type: ignore[arg-type]

    full_rebuild.assert_not_called()
    cheap_path.assert_called_once_with(4, 5)


def test_update_state_full_rebuild_when_stable_state_changes() -> None:
    """A metric change still triggers ``_update_display`` (full rebuild)."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(running=2))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**stable_state_kwargs(running=3))  # type: ignore[arg-type]

    full_rebuild.assert_called_once()
    cheap_path.assert_not_called()


def test_update_state_routes_unchanged_neighbor_count_to_countdown_only() -> None:
    """Unchanged neighbor count is part of stable state, not countdown churn."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(neighbor_count=2, countdown=5))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**stable_state_kwargs(neighbor_count=2, countdown=4))  # type: ignore[arg-type]

    full_rebuild.assert_not_called()
    cheap_path.assert_called_once_with(4, 5)


def test_update_state_full_rebuild_when_neighbor_count_changes() -> None:
    """Neighbor-count changes rebuild the stable badge text."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(neighbor_count=1))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**stable_state_kwargs(neighbor_count=2))  # type: ignore[arg-type]

    full_rebuild.assert_called_once()
    cheap_path.assert_not_called()


def test_update_state_full_rebuild_when_runner_capacity_changes() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(runner_queue_count=0))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**stable_state_kwargs(runner_queue_count=1))  # type: ignore[arg-type]

    full_rebuild.assert_called_once()
    cheap_path.assert_not_called()


def test_render_and_countdown_paths_do_not_read_runner_configuration() -> None:
    panel = AgentInfoPanel()
    with patch(
        "sase.config.core.get_max_running_agents",
        side_effect=AssertionError("render path read configuration"),
    ):
        collect_text(panel)
        with patch.object(panel, "update"):
            panel.update_countdown_only(4, 5)


def test_update_display_uses_layout_false() -> None:
    """Full panel rebuilds also opt out of layout, since the bar is 1 line."""
    panel = AgentInfoPanel()
    calls: list[dict[str, object]] = []

    def fake_update(text: Text, **kwargs: object) -> None:
        calls.append({"text": text, **kwargs})

    with patch.object(panel, "update", side_effect=fake_update):
        panel._update_display()

    assert calls
    assert calls[-1]["layout"] is False

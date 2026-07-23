"""Tests for the Agents-tab info panel rendering."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.keymaps import key_display_name, load_keymap_registry
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel

_DEFAULT_GROUPING_KEY = key_display_name(
    load_keymap_registry({}).app.cycle_grouping_mode
)
_DEFAULT_NEIGHBOR_KEY = key_display_name(
    load_keymap_registry({}).app.start_sibling_mode
)


def _collect_text(panel: AgentInfoPanel) -> str:
    captured: list[str] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text.plain),
    ):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def _collect_rich_text(panel: AgentInfoPanel) -> Text:
    captured: list[Text] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text),
    ):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def _style_for_plain_segment(text: Text, segment: str) -> str:
    start = text.plain.index(segment)
    end = start + len(segment)
    matching = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
    assert matching, f"no Rich style span found for {segment!r}"
    return matching[-1]


def _style_at_plain_index(text: Text, index: int) -> str:
    matching = [
        str(span.style) for span in text.spans if span.start <= index < span.end
    ]
    assert matching, f"no Rich style span found at index {index}"
    return matching[-1]


def test_grouping_badge_renders_by_project_when_unset() -> None:
    """The badge always renders, treating an empty label as ``by project``."""
    panel = AgentInfoPanel()
    plain = _collect_text(panel)
    assert f"[group: by project ({_DEFAULT_GROUPING_KEY})]" in plain


def test_agent_lane_headline_renders_before_concrete_metrics() -> None:
    panel = AgentInfoPanel()
    panel._position = 2
    panel._total = 12
    panel._unread_count = 3
    panel._asking_count = 2
    panel._running_count = 5
    panel._waiting_count = 2
    panel._failed_count = 1
    panel._read_count = 0
    panel._agent_lane_count = 12

    plain = _collect_text(panel)

    assert plain.startswith(
        "12  [0/0 · 0 queued]  "
        "[2 stopped · 5 running · 2 waiting · 1 failed · 3 unread]"
    )
    assert "Agents: 2/12" not in plain


def test_agent_count_strip_reports_starting_separately() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_agent_counts(
            unread=1,
            asking=2,
            running=3,
            waiting=4,
            failed=5,
            read=6,
            total=12,
            starting=7,
        )

    plain = _collect_text(panel)

    assert plain.startswith(
        "12  [0/0 · 0 queued]  "
        "[2 stopped · 7 starting · 3 running · "
        "4 waiting · 5 failed · 1 unread · 6 done]"
    )


def test_agent_count_numbers_have_rich_styles() -> None:
    panel = AgentInfoPanel()
    panel._agent_lane_count = 20
    panel._asking_count = 31
    panel._starting_count = 37
    panel._running_count = 42
    panel._waiting_count = 53
    panel._unread_count = 64
    panel._read_count = 75
    panel._failed_count = 86

    text = _collect_rich_text(panel)

    count_styles = {
        "total": _style_for_plain_segment(text, "20"),
        "asking": _style_for_plain_segment(text, "31"),
        "starting": _style_for_plain_segment(text, "37"),
        "running": _style_for_plain_segment(text, "42"),
        "waiting": _style_for_plain_segment(text, "53"),
        "failed": _style_for_plain_segment(text, "86"),
        "unread": _style_for_plain_segment(text, "64"),
        "read": _style_for_plain_segment(text, "75"),
    }
    assert count_styles == {
        "total": "bold #FFFFFF",
        "asking": "bold #FFAF00",
        "starting": "bold #1a1a1a on #87D7FF",
        "running": "bold #00D7AF",
        "waiting": "bold #AF87FF",
        "failed": "bold #FF5F5F",
        "unread": "bold #1a1a1a on #FFD700",
        "read": "bold #5FD7FF",
    }

    label_styles = {
        " stopped": _style_for_plain_segment(text, " stopped"),
        " starting": _style_for_plain_segment(text, " starting"),
        " running": _style_for_plain_segment(text, " running"),
        " waiting": _style_for_plain_segment(text, " waiting"),
        " failed": _style_for_plain_segment(text, " failed"),
        " unread": _style_for_plain_segment(text, " unread"),
        " done": _style_for_plain_segment(text, " done"),
    }
    assert label_styles == {
        " stopped": "dim",
        " starting": "bold #1a1a1a on #87D7FF",
        " running": "dim",
        " waiting": "dim",
        " failed": "dim",
        " unread": "bold #1a1a1a on #FFD700",
        " done": "dim",
    }


def test_update_agent_counts_uses_plain_metric_text() -> None:
    panel = AgentInfoPanel()

    captured: list[str] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text.plain),
    ):
        panel.update_agent_counts(1, 2, 3, 4, 5, 6, 10)
    assert captured, "panel.update_agent_counts did not refresh the display"
    plain = captured[-1]

    assert (
        "10  [0/0 · 0 queued]  "
        "[2 stopped · 3 running · 4 waiting · 5 failed · 1 unread · 6 done]"
    ) in plain
    assert "Agents(" not in plain
    assert "#FFAF5F" not in plain
    assert " read" not in plain


def test_agent_count_strip_omits_zero_metric_types() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_agent_counts(
            unread=2,
            asking=0,
            running=3,
            waiting=0,
            failed=1,
            read=0,
            total=9,
        )

    plain = _collect_text(panel)
    counts_prefix = plain.split("   [group:", 1)[0]

    assert plain.startswith("9  [0/0 · 0 queued]  [3 running · 1 failed · 2 unread]")
    assert "stopped" not in counts_prefix
    assert "waiting" not in counts_prefix
    assert " done" not in counts_prefix


def test_agent_count_strip_omits_metrics_section_when_all_counts_are_zero() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_agent_counts(
            unread=0,
            asking=0,
            running=0,
            waiting=0,
            failed=0,
            read=0,
            total=5,
        )

    plain = _collect_text(panel)
    counts_prefix = plain.split("   [group:", 1)[0]

    assert counts_prefix == "5  [0/0 · 0 queued]"


def test_runner_capacity_chip_exact_copy_and_zero_queue_visibility() -> None:
    panel = AgentInfoPanel()
    panel._agent_lane_count = 12
    panel._runner_slots_in_use = 8
    panel._runner_limit = 10
    panel._runner_queue_count = 0

    plain = _collect_text(panel)

    assert plain.startswith("12  [8/10 · 0 queued]")


def test_runner_capacity_chip_uses_plural_neutral_queue_wording() -> None:
    panel = AgentInfoPanel()
    panel._runner_slots_in_use = 10
    panel._runner_limit = 10
    panel._runner_queue_count = 1

    plain = _collect_text(panel)

    assert "[10/10 · 1 queued]" in plain
    assert "1 queue" not in plain.replace("1 queued", "")


def test_runner_capacity_chip_styles_below_at_and_above_limit() -> None:
    panel = AgentInfoPanel()
    panel._runner_limit = 10
    panel._runner_queue_count = 7

    expected_occupancy_styles = {
        8: "bold #00D7AF",
        10: "bold #FFD700",
        12: "bold #FF5F5F",
    }
    for slots_in_use, expected_style in expected_occupancy_styles.items():
        panel._runner_slots_in_use = slots_in_use
        text = _collect_rich_text(panel)
        capacity_segment = f"{slots_in_use}/{panel._runner_limit}"
        occupancy_index = text.plain.index(capacity_segment)
        slash_index = text.plain.index("/", occupancy_index)
        limit_index = slash_index + 1
        queue_index = text.plain.index("7 queued", limit_index)
        assert _style_at_plain_index(text, occupancy_index) == expected_style
        assert _style_at_plain_index(text, slash_index) == "dim"
        assert _style_at_plain_index(text, limit_index) == "bold #87D7FF"
        assert _style_at_plain_index(text, queue_index) == "bold #AF87FF"

    panel._runner_slots_in_use = 8
    panel._runner_queue_count = 0
    zero_text = _collect_rich_text(panel)
    zero_queue_index = zero_text.plain.index("0 queued")
    assert _style_at_plain_index(zero_text, zero_queue_index) == "dim"


def test_neighbor_badge_is_omitted_without_visible_neighbors() -> None:
    panel = AgentInfoPanel()
    panel._agent_lane_count = 5
    panel._neighbor_count = 0

    plain = _collect_text(panel)

    assert "neighbors:" not in plain


def test_neighbor_badge_renders_single_visible_neighbor() -> None:
    panel = AgentInfoPanel()
    panel._agent_lane_count = 5
    panel._neighbor_count = 1

    plain = _collect_text(panel)

    assert f"[neighbors: 1 ({_DEFAULT_NEIGHBOR_KEY})]" in plain


def test_neighbor_badge_renders_multiple_visible_neighbors_with_styles() -> None:
    panel = AgentInfoPanel()
    panel._agent_lane_count = 5
    panel._neighbor_count = 3

    text = _collect_rich_text(panel)

    assert f"[neighbors: 3 ({_DEFAULT_NEIGHBOR_KEY})]" in text.plain
    assert _style_for_plain_segment(text, "3") == "bold #00D7AF"


def test_neighbor_badge_uses_active_keymap_registry() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.set_keymap_registry(
            load_keymap_registry({"keymaps": {"app": {"start_sibling_mode": "f2"}}})
        )
    panel._agent_lane_count = 5
    panel._neighbor_count = 2

    plain = _collect_text(panel)

    assert "[neighbors: 2 (f2)]" in plain


def test_grouping_badge_renders_label_after_update() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by status"
    plain = _collect_text(panel)
    assert f"[group: by status ({_DEFAULT_GROUPING_KEY})]" in plain


def test_grouping_badge_renders_by_date_label() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by date"
    plain = _collect_text(panel)
    assert f"[group: by date ({_DEFAULT_GROUPING_KEY})]" in plain


def test_summary_view_badge_is_visible_and_gold() -> None:
    panel = AgentInfoPanel()
    panel._view_mode = "summary"

    text = _collect_rich_text(panel)

    assert "[view: summary]" in text.plain
    assert _style_for_plain_segment(text, "summary") == "bold #FFD75F"


def test_grouping_badge_suppressed_while_loading() -> None:
    """Loading state short-circuits before the badge segment is emitted."""
    panel = AgentInfoPanel()
    panel._loading = True
    plain = _collect_text(panel)
    assert "group:" not in plain


def test_count_strip_suppressed_while_loading() -> None:
    panel = AgentInfoPanel()
    panel._loading = True
    panel._unread_count = 3
    panel._asking_count = 2
    panel._running_count = 5
    panel._waiting_count = 2
    panel._failed_count = 1
    panel._read_count = 2
    panel._agent_lane_count = 12

    plain = _collect_text(panel)

    assert plain == "Agents: …"
    assert "unread" not in plain
    assert "failed" not in plain


def _stable_state_kwargs(**overrides: object) -> dict[str, object]:
    """Default kwargs for ``AgentInfoPanel.update_state``."""
    base: dict[str, object] = {
        "position": 0,
        "total": 5,
        "unread": 0,
        "asking": 0,
        "running": 2,
        "waiting": 0,
        "failed": 0,
        "read": 0,
        "agent_lane_count": 5,
        "starting": 0,
        "neighbor_count": 0,
        "countdown": 5,
        "interval": 5,
        "view_mode": "",
        "grouping_mode": "by project",
        "search_query": "",
        "runner_limit": 10,
        "runner_slots_in_use": 2,
        "runner_queue_count": 0,
    }
    base.update(overrides)
    return base


def test_update_state_renders_supplied_agent_lane_count_unchanged() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(
            **_stable_state_kwargs(
                agent_lane_count=4,
                running=3,
                read=3,
            )
        )  # type: ignore[arg-type]

    plain = _collect_text(panel)

    assert plain.startswith("4  [2/10 · 0 queued]  [3 running · 3 done]")


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
        panel.update_state(**_stable_state_kwargs(countdown=5))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**_stable_state_kwargs(countdown=4))  # type: ignore[arg-type]

    full_rebuild.assert_not_called()
    cheap_path.assert_called_once_with(4, 5)


def test_update_state_full_rebuild_when_stable_state_changes() -> None:
    """A metric change still triggers ``_update_display`` (full rebuild)."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**_stable_state_kwargs(running=2))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**_stable_state_kwargs(running=3))  # type: ignore[arg-type]

    full_rebuild.assert_called_once()
    cheap_path.assert_not_called()


def test_update_state_routes_unchanged_neighbor_count_to_countdown_only() -> None:
    """Unchanged neighbor count is part of stable state, not countdown churn."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**_stable_state_kwargs(neighbor_count=2, countdown=5))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**_stable_state_kwargs(neighbor_count=2, countdown=4))  # type: ignore[arg-type]

    full_rebuild.assert_not_called()
    cheap_path.assert_called_once_with(4, 5)


def test_update_state_full_rebuild_when_neighbor_count_changes() -> None:
    """Neighbor-count changes rebuild the stable badge text."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**_stable_state_kwargs(neighbor_count=1))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**_stable_state_kwargs(neighbor_count=2))  # type: ignore[arg-type]

    full_rebuild.assert_called_once()
    cheap_path.assert_not_called()


def test_update_state_full_rebuild_when_runner_capacity_changes() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**_stable_state_kwargs(runner_queue_count=0))  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**_stable_state_kwargs(runner_queue_count=1))  # type: ignore[arg-type]

    full_rebuild.assert_called_once()
    cheap_path.assert_not_called()


def test_render_and_countdown_paths_do_not_read_runner_configuration() -> None:
    panel = AgentInfoPanel()
    with patch(
        "sase.config.core.get_max_running_agents",
        side_effect=AssertionError("render path read configuration"),
    ):
        _collect_text(panel)
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

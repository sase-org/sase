"""Tests for Agents-tab info panel element grammar."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.keymaps import load_keymap_registry

from ._agent_info_panel_helpers import (
    DEFAULT_GROUPING_KEY,
    DEFAULT_REFRESH_KEY,
    DEFAULT_VIEW_KEY,
    AgentInfoPanel,
    collect_rich_text,
    collect_text,
    stable_state_kwargs,
    style_at_plain_index,
)


def _representative_panel() -> AgentInfoPanel:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(
            **stable_state_kwargs(
                sase_agent_count=12,
                running=4,
                runner_queue_count=1,
                read=3,
                view_mode="none",
                view_picker_available=True,
                grouping_mode="by status",
                countdown=7,
                interval=10,
            )
        )  # type: ignore[arg-type]
    return panel


def test_full_row_uses_dot_grammar_without_bracketed_badges() -> None:
    panel = _representative_panel()
    plain = collect_text(panel)

    assert f"view: none ({DEFAULT_VIEW_KEY})" in plain
    assert f"group: by status ({DEFAULT_GROUPING_KEY})" in plain
    assert f"refresh: 7s ({DEFAULT_REFRESH_KEY})" in plain
    assert (
        f"view: none ({DEFAULT_VIEW_KEY}) · group: by status ({DEFAULT_GROUPING_KEY}) "
        f"· refresh: 7s ({DEFAULT_REFRESH_KEY})"
    ) in plain
    assert "   " not in plain
    assert "[group" not in plain
    assert "[view" not in plain
    assert plain.count("[") == 1
    assert plain.count("]") == 1


def test_separators_are_dim() -> None:
    panel = _representative_panel()
    text = collect_rich_text(panel)

    index = 0
    found = 0
    while True:
        at = text.plain.find(" · ", index)
        if at < 0:
            break
        found += 1
        assert style_at_plain_index(text, at + 1) == "dim"
        index = at + 3
    assert found >= 3


def test_filter_and_partial_history_join_with_dot_and_keep_click_span() -> None:
    panel = AgentInfoPanel()
    highlighted = Text("status:FAILED")
    with patch.object(panel, "update"):
        panel.update_search_query(
            "status:FAILED",
            rich=highlighted,
            match_count=(1, 5),
            partial_history=True,
        )

    text = collect_rich_text(panel)

    assert " · filter: status:FAILED  1/5  filtered on recent history;" in text.plain
    assert panel._search_query_click_span is not None
    start, end = panel._search_query_click_span
    assert text.plain[start:end] == "status:FAILED  1/5"


def test_unbound_refresh_omits_hint() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.set_keymap_registry(
            load_keymap_registry({"keymaps": {"app": {"agents_refresh": "unbound"}}})
        )
        panel.update_countdown(4, 5)

    plain = collect_text(panel)

    assert "refresh: 4s" in plain
    assert "refresh: 4s (" not in plain


def test_zero_interval_omits_refresh_without_trailing_separator() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(countdown=0, interval=0))  # type: ignore[arg-type]

    plain = collect_text(panel)

    assert "refresh:" not in plain
    assert not plain.endswith(" · ")
    assert not plain.endswith("·")
    assert "   " not in plain


def test_update_countdown_only_patches_refresh_template() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(countdown=5))  # type: ignore[arg-type]

    calls: list[dict[str, object]] = []

    def fake_update(text: Text, **kwargs: object) -> None:
        calls.append({"text": text, **kwargs})

    with (
        patch.object(panel, "_build_display_text") as full_builder,
        patch.object(panel, "update", side_effect=fake_update),
    ):
        panel.update_countdown_only(4, 5)

    full_builder.assert_not_called()
    assert len(calls) == 1
    plain = calls[0]["text"].plain  # type: ignore[union-attr]
    assert f"refresh: 4s ({DEFAULT_REFRESH_KEY})" in plain
    assert f"refresh: 5s ({DEFAULT_REFRESH_KEY})" not in plain

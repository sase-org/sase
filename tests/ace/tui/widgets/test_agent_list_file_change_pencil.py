"""Tests for agent list file change pencil rendering."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.widgets._agent_display_helpers import (
    clear_bead_display_cache,
    confirm_bead,
    make_agent,
)

pytestmark = pytest.mark.usefixtures("clear_bead_display_cache")


class TestAgentListFileChangePencil:
    def test_row_with_diff_path_renders_pencil(self) -> None:
        agent = make_agent(diff_path="/tmp/sase/demo.diff", llm_provider=None)

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_row_with_classified_real_diff_renders_pencil(self) -> None:
        agent = make_agent(
            diff_path="/tmp/sase/demo.diff",
            diff_has_real_edits=True,
            llm_provider=None,
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_row_with_classified_bookkeeping_diff_omits_pencil(self) -> None:
        agent = make_agent(
            diff_path="/tmp/sase/demo.diff",
            diff_has_real_edits=False,
            llm_provider=None,
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert "✏️" not in suffix.plain

    def test_row_without_diff_path_omits_pencil(self) -> None:
        agent = make_agent()

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert "✏️" not in suffix.plain

    def test_row_with_live_hint_renders_pencil_without_diff_path(self) -> None:
        agent = make_agent(live_file_change_hint=True, llm_provider=None)

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_row_with_false_live_hint_omits_pencil(self) -> None:
        agent = make_agent(live_file_change_hint=False, llm_provider=None)

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert "✏️" not in suffix.plain

    def test_row_with_linked_file_change_hint_renders_pencil(self) -> None:
        agent = make_agent(linked_file_change_hint=True, llm_provider=None)

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_row_with_false_linked_file_change_hint_omits_pencil(self) -> None:
        agent = make_agent(linked_file_change_hint=False, llm_provider=None)

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert "✏️" not in suffix.plain

    def test_linked_change_overrides_bookkeeping_primary_diff(self) -> None:
        agent = make_agent(
            diff_path="/tmp/sase/demo.diff",
            diff_has_real_edits=False,
            linked_file_change_hint=True,
            llm_provider=None,
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_active_live_hint_wins_over_persisted_classification(self) -> None:
        # A persisted bookkeeping-only classification is only a fallback while
        # the row is active; fresh live workspace edits drive the pencil.
        agent = make_agent(
            diff_path="/tmp/sase/demo.diff",
            diff_has_real_edits=False,
            live_file_change_hint=True,
            llm_provider=None,
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_pencil_renders_in_suffix_not_display_name_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(
            agent_name="sase-x.3",
            diff_path="/tmp/sase/demo.diff",
            tag="pinned",
        )
        confirm_bead(agent, monkeypatch)

        left, suffix, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            fold_annotation="×3",
            tribe_label="fix",
        )

        assert "test_cl @fix (RUNNING)×3 ◆ sase-x.3" in left.plain
        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"
        assert "[pinned]" not in left.plain

    def test_running_pencil_immediately_follows_runtime_marker(self) -> None:
        start = datetime(2026, 4, 25, 14, 0, 0)
        agent = make_agent(
            diff_path="/tmp/sase/demo.diff",
            llm_provider=None,
            run_start_time=start,
        )

        left, suffix, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            now=datetime(2026, 4, 25, 14, 1, 23),
        )

        assert "✏️" not in left.plain
        assert suffix.plain == "🏃‍♂️ 1m23s ✏️"

    def test_finished_pencil_immediately_follows_finish_timestamp(self) -> None:
        agent = make_agent(
            status="DONE",
            start_time=datetime(2026, 4, 24, 19, 38, 18),
            stop_time=datetime(2026, 4, 24, 20, 17, 3),
            diff_path="/tmp/sase/demo.diff",
            llm_provider=None,
        )

        left, suffix, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            now=datetime(2026, 4, 25, 9, 0, 0),
        )

        assert "✏️" not in left.plain
        assert suffix.plain == "Apr 24 20:17 · 38m45s ✏️"

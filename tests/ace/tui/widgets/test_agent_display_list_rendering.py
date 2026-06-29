"""Tests for agent display list and phase rendering."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bead import _BEAD_DISPLAY_CACHE, resolve_bead_display
from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_header_text,
    render_phase_divider,
)
from sase.bead.model import Issue
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_bead_display_cache() -> Iterator[None]:
    _BEAD_DISPLAY_CACHE.clear()
    yield
    _BEAD_DISPLAY_CACHE.clear()


def _confirm_bead(agent, monkeypatch: pytest.MonkeyPatch) -> None:
    """Warm the confirmation cache so the row renders the bead glyph."""
    monkeypatch.setattr(
        "sase.agent.bead_display._lookup_bead_issue",
        lambda candidate_id, **_: Issue(id=candidate_id, title="", description=""),
    )
    resolve_bead_display(agent)


class TestAgentListBeadBadge:
    def test_confirmed_phase_agent_row_renders_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        _confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ sase-x.3" in left.plain

    def test_confirmed_land_agent_row_renders_epic_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.land")
        _confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ sase-x.land" in left.plain

    def test_confirmed_exact_land_agent_row_renders_epic_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x")
        _confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ sase-x" in left.plain

    def test_confirmed_dismissed_phase_agent_row_renders_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="260428.sase-x.3")
        _confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ 260428.sase-x.3" in left.plain

    def test_cold_bead_candidate_row_omits_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Bead-shaped name, but the cache has not confirmed it exists yet. Row
        # formatting must never touch bead storage to decide the glyph.
        agent = make_agent(agent_name="sase-x.3")

        def fail_lookup(candidate_id: str, **_: object) -> Issue | None:
            raise AssertionError("row formatting must not touch bead storage")

        monkeypatch.setattr("sase.agent.bead_display._lookup_bead_issue", fail_lookup)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_missing_bead_candidate_row_omits_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda candidate_id, **_: None,
        )
        resolve_bead_display(agent)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="reviewer")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_dotted_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="aij.2")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain
        assert " aij.2" in left.plain
        assert "[aij.2]" not in left.plain

    def test_bead_badge_flows_from_fold_annotation_to_agent_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3", tag="pinned")
        _confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(
            agent, 0, is_selected=False, fold_annotation="×3"
        )

        assert "(RUNNING)×3 ◆ sase-x.3" in left.plain
        assert "[pinned]" not in left.plain


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

    def test_persisted_classification_wins_over_live_hint(self) -> None:
        # A persisted bookkeeping-only classification stays authoritative even
        # if a stale live hint says otherwise.
        agent = make_agent(
            diff_path="/tmp/sase/demo.diff",
            diff_has_real_edits=False,
            live_file_change_hint=True,
            llm_provider=None,
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "✏️" not in left.plain
        assert "✏️" not in suffix.plain

    def test_pencil_renders_in_suffix_not_display_name_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(
            agent_name="sase-x.3",
            diff_path="/tmp/sase/demo.diff",
            tag="pinned",
        )
        _confirm_bead(agent, monkeypatch)

        left, suffix, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            fold_annotation="×3",
            tag_label="fix",
        )

        assert "test_cl #fix (RUNNING)×3 ◆ sase-x.3" in left.plain
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


class TestAgentListRevertedIndicator:
    def test_root_row_renders_reverted_badge_and_struck_name(self) -> None:
        agent = make_agent(status="DONE", reverted=True, llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=True)

        assert "↺ test_cl (DONE)" in left.plain
        name_start = left.plain.index("test_cl")
        name_end = name_start + len("test_cl")
        assert any(
            span.start <= name_start
            and span.end >= name_end
            and "strike" in str(span.style).lower()
            and "bold" in str(span.style).lower()
            and "#00d7af" in str(span.style).lower()
            for span in left.spans
        )

    def test_workflow_child_omits_reverted_indicator(self) -> None:
        agent = make_agent(
            status="DONE",
            reverted=True,
            parent_workflow="parent",
            step_type="agent",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "↺" not in left.plain
        name_start = left.plain.index("test_cl")
        name_end = name_start + len("test_cl")
        assert not any(
            span.start <= name_start
            and span.end >= name_end
            and "strike" in str(span.style).lower()
            for span in left.spans
        )

    def test_normal_row_omits_reverted_indicator(self) -> None:
        agent = make_agent(status="DONE", llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "↺" not in left.plain


class TestAgentListAutoApproveIcon:
    def test_normal_auto_approve_renders_bare_bolt(self) -> None:
        agent = make_agent(approve=True, llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("⚡ ")
        assert "⚡E" not in left.plain
        assert "⚡T" not in left.plain
        assert "test_cl (RUNNING)" in left.plain

    def test_tale_auto_approve_renders_bolt_t(self) -> None:
        agent = make_agent(
            approve=True, auto_approve_plan_action="tale", llm_provider=None
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("⚡T ")
        assert "test_cl (RUNNING)" in left.plain

    def test_epic_auto_approve_renders_bolt_e(self) -> None:
        agent = make_agent(
            approve=True, auto_approve_plan_action="epic", llm_provider=None
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("⚡E ")
        assert "test_cl (RUNNING)" in left.plain

    def test_non_approve_row_omits_bolt(self) -> None:
        agent = make_agent(llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "⚡" not in left.plain


class TestAwareWaitUntilRendering:
    def test_agent_row_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "WAITING (until " in left.plain
        assert "," in left.plain

    def test_header_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        header, _ = build_header_text(agent, cheap=True)

        assert "Wait: until " in header.plain
        assert " left)" in header.plain


class TestStartingStatusRendering:
    def test_agent_row_renders_starting_status_with_distinct_style(self) -> None:
        agent = make_agent(status="STARTING")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "(STARTING)" in left.plain
        status_start = left.plain.index("STARTING")
        status_end = status_start + len("STARTING")
        assert any(
            span.start <= status_start
            and span.end >= status_end
            and str(span.style) == "bold #87D7FF"
            for span in left.spans
        )


class TestStoppedStatusRendering:
    def test_agent_row_renders_stopped_status_with_glyph_and_style(self) -> None:
        agent = make_agent(status=STOPPED_STATUS)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        stopped_text = f"{STOPPED_GLYPH} {STOPPED_STATUS}"
        assert f"({stopped_text})" in left.plain
        status_start = left.plain.index(stopped_text)
        status_end = status_start + len(stopped_text)
        assert any(
            span.start <= status_start
            and span.end >= status_end
            and str(span.style) == f"bold {STOPPED_COLOR}"
            for span in left.spans
        )


# -- provider emoji badges ----------------------------------------------------


class TestAgentListProviderEmojiBadges:
    def test_root_row_renders_child_provider_emojis_before_name(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider=None,
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        planner = make_agent(
            cl_name="planner",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        coder = make_agent(
            cl_name="coder",
            llm_provider="codex",
            start_time=datetime(2024, 1, 1, 14, 5, 0),
        )
        root.runtime_children.extend([planner, coder])

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🤖 root-agent (RUNNING)" in left.plain

    def test_root_row_provider_order_follows_first_run_time(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider=None,
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        agy = make_agent(
            cl_name="agy",
            llm_provider="agy",
            start_time=datetime(2024, 1, 1, 14, 6, 0),
        )
        codex = make_agent(
            cl_name="codex",
            llm_provider="codex",
            start_time=datetime(2024, 1, 1, 14, 3, 0),
        )
        claude = make_agent(
            cl_name="claude",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        root.runtime_children.extend([agy, codex, claude])

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🤖 🪐 root-agent (RUNNING)" in left.plain

    def test_root_row_deduplicates_provider_emojis(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        planner = make_agent(
            cl_name="planner",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        coder = make_agent(
            cl_name="coder",
            llm_provider="codex",
            start_time=datetime(2024, 1, 1, 14, 5, 0),
        )
        root.runtime_children.extend([planner, coder])

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🤖 root-agent (RUNNING)" in left.plain
        assert left.plain.count("🎭") == 1

    def test_root_row_skips_providerless_child_and_includes_grandchild(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        child = make_agent(
            cl_name="child",
            llm_provider=None,
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        grandchild = make_agent(
            cl_name="grandchild",
            llm_provider="agy",
            start_time=datetime(2024, 1, 1, 14, 2, 0),
        )
        child.runtime_children.append(grandchild)
        root.runtime_children.append(child)

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🪐 root-agent (RUNNING)" in left.plain

    def test_root_row_renders_opencode_provider_emoji_before_name(self) -> None:
        agent = make_agent(cl_name="root-agent", llm_provider="opencode")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "🐙 root-agent (RUNNING)" in left.plain

    def test_root_row_keeps_provider_before_name_and_moves_pencil_to_suffix(
        self,
    ) -> None:
        agent = make_agent(
            cl_name="root-agent",
            llm_provider="opencode",
            diff_path="/tmp/sase/demo.diff",
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "🐙 root-agent (RUNNING)" in left.plain
        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_root_row_renders_qwen_provider_emoji_after_prefix_controls(self) -> None:
        agent = make_agent(cl_name="qwen-agent", llm_provider="qwen")

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            is_marked=True,
            hint_char="a",
        )

        assert left.plain.startswith("[a] [✓] [agent] 🐼 qwen-agent")

    def test_workflow_child_row_renders_codex_provider_emoji_before_name(self) -> None:
        agent = make_agent(
            cl_name="child-agent",
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="agent",
            step_type="agent",
            step_index=0,
            total_steps=2,
            llm_provider="codex",
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "1/2 🤖 child-agent (RUNNING)" in left.plain

    def test_non_agent_workflow_child_row_omits_provider_emoji(self) -> None:
        agent = make_agent(
            cl_name="diff",
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="diff",
            step_type="bash",
            step_index=0,
            total_steps=2,
            llm_provider="claude",
            diff_path="/tmp/sase/demo.diff",
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "1/2 🐚 diff (RUNNING)" in left.plain
        assert "🎭" not in left.plain
        assert suffix.plain == "✏️"

    def test_row_without_provider_omits_provider_emoji(self) -> None:
        agent = make_agent(cl_name="plain-agent", llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain == "[agent] plain-agent (RUNNING)"
        assert not any(emoji in left.plain for emoji in ("🎭", "🪐", "🤖", "🐼", "🐙"))


# -- _render_phase_divider ----------------------------------------------------


class TestRenderPhaseDivider:
    def test_contains_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1, 14, 23, 45))
        assert "PLANNER" in divider.plain

    def test_contains_time_format(self) -> None:
        divider = render_phase_divider("CODER", datetime(2024, 1, 1, 14, 23, 45))
        assert re.search(r"\d{2}:\d{2}:\d{2}", divider.plain)

    def test_none_start_time(self) -> None:
        divider = render_phase_divider("AGENT", None)
        assert "??:??:??" in divider.plain

    def test_bold_purple_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1))
        has_bold = any(
            "bold" in str(s.style) and "af87ff" in str(s.style).lower()
            for s in divider._spans
        )
        assert has_bold


# -- workflow step-type glyphs -------------------------------------------------


class TestWorkflowStepTypeGlyph:
    def _make_child(self, step_type: str) -> Agent:
        return make_agent(
            parent_workflow="olcr",
            step_name=step_type,
            step_type=step_type,
            step_index=0,
            total_steps=3,
        )

    def test_python_step_renders_snake_glyph(self) -> None:
        agent = self._make_child("python")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "1/3 \U0001f40d " in left.plain

    def test_bash_step_renders_shell_glyph(self) -> None:
        agent = self._make_child("bash")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "1/3 \U0001f41a " in left.plain

    def test_agent_step_has_no_step_type_glyph(self) -> None:
        agent = self._make_child("agent")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "\U0001f40d" not in left.plain
        assert "\U0001f41a" not in left.plain

    def test_parallel_step_has_no_step_type_glyph(self) -> None:
        agent = self._make_child("parallel")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "\U0001f40d" not in left.plain
        assert "\U0001f41a" not in left.plain


# -- followup_agents field -----------------------------------------------------

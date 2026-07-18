"""Fold-aware family-container detail panel tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel import _agent_display_render
from sase.ace.tui.widgets.prompt_panel._agent_display_family import (
    FAMILY_PROMPT_SECTION_ID,
    FAMILY_REPLY_SECTION_ID,
    FAMILY_XPROMPT_SECTION_ID,
    _family_roster_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of


def _family(
    tmp_path: Path,
    *,
    in_clan: bool = False,
) -> tuple[Agent, Agent]:
    started = datetime(2026, 7, 18, 12, 0, 0)
    root_dir = tmp_path / ("clan-plan" if in_clan else "standalone-plan")
    child_dir = tmp_path / ("clan-code" if in_clan else "standalone-code")
    root_dir.mkdir()
    child_dir.mkdir()
    _write_phase_content(root_dir, "plan")
    _write_phase_content(child_dir, "code")

    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family-test",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started,
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260718120000",
        artifacts_dir=str(root_dir),
        response_path=str(root_dir / "response.md"),
        agent_name="alpha--plan",
        agent_family="alpha",
        agent_family_role="plan",
        role_suffix="--plan",
        plan_chain_root=True,
        model="claude/opus",
        agent_clan="map" if in_clan else None,
        output_variables={"plan_path": "/tmp/plan.md"},
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family-test",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started + timedelta(minutes=2),
        stop_time=started + timedelta(minutes=5),
        raw_suffix="20260718120200",
        artifacts_dir=str(child_dir),
        response_path=str(child_dir / "response.md"),
        agent_name="alpha--code",
        agent_family="alpha",
        agent_family_role="code",
        role_suffix="--code",
        model="claude/sonnet",
        agent_clan="map" if in_clan else None,
        output_variables={"code_path": "/tmp/code.md"},
    )
    root.followup_agents = [child]
    assert root.is_family_container_row is True
    return root, child


def _write_phase_content(directory: Path, role: str) -> None:
    (directory / "raw_xprompt.md").write_text(
        "\n".join(f"{role} xprompt line {index}" for index in range(1, 16)) + "\n",
        encoding="utf-8",
    )
    (directory / "01_prompt.md").write_text(
        "\n".join(f"{role} prompt line {index}" for index in range(1, 16)) + "\n",
        encoding="utf-8",
    )
    (directory / "response.md").write_text(
        "\n".join(f"{role} reply line {index}" for index in range(1, 7)) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("in_clan", [False, True])
def test_family_roster_numbers_real_chain_rows_in_order(
    tmp_path: Path,
    in_clan: bool,
) -> None:
    root, child = _family(tmp_path, in_clan=in_clan)

    entries = _family_roster_entries(root, now=root.stop_time)
    published = []
    header, _ = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
    )

    assert [entry.identity for entry in entries] == [root.identity, child.identity]
    assert [entry.label for entry in entries] == ["--plan", "--code"]
    assert [entry.kind for entry in entries] == ["PLANNER", "CODER"]
    assert "▸ ❖ FAMILY MEMBERS · 2\n" in header.plain
    assert header.plain.index("FAMILY MEMBERS") < header.plain.index("OUTPUT VARIABLES")
    assert [target.member_identity for target in published[0].targets] == [
        root.identity,
        child.identity,
    ]


def test_collapsed_family_sections_do_not_read_prompt_or_reply_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, child = _family(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("collapsed family detail performed a content read")

    monkeypatch.setattr(root, "get_raw_xprompt_content", fail)
    monkeypatch.setattr(_agent_display_render, "get_prompt_content", fail)
    for phase in (root, child):
        monkeypatch.setattr(phase, "get_timestamped_reply_chunks", fail)
        monkeypatch.setattr(phase, "get_live_reply_content", fail)
        monkeypatch.setattr(phase, "get_response_content", fail)
        monkeypatch.setattr(phase, "get_chat_response_content", fail)

    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▸ AGENT XPROMPT\ncontent deferred" in plain
    assert "▸ AGENT PROMPT\ncontent deferred" in plain
    assert "▸ AGENT REPLY · 2\n" in plain
    assert "PLANNER · ✓ DONE · 12:00:00" in plain
    assert "CODER · ✓ DONE · 12:02:00" in plain


def test_expanded_family_sections_render_bounded_previews(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.EXPANDED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 12" in plain
    assert "… +3 more lines" in plain
    assert "plan xprompt line 15" not in plain
    assert "plan prompt line 12" in plain
    assert "plan prompt line 15" not in plain
    assert "plan reply line 1" not in plain
    assert "plan reply line 6" in plain
    assert "… +2 earlier lines" in plain


def test_collapsing_after_preview_reuses_one_line_content_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, child = _family(tmp_path)
    panel = FakePromptPanel()
    expanded, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.EXPANDED,
    )
    panel._update_family_display(
        root,
        expanded,
        error,
        panel_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cached collapsed digest performed a content read")

    monkeypatch.setattr(root, "get_raw_xprompt_content", fail)
    monkeypatch.setattr(_agent_display_render, "get_prompt_content", fail)
    for phase in (root, child):
        monkeypatch.setattr(phase, "get_timestamped_reply_chunks", fail)
        monkeypatch.setattr(phase, "get_live_reply_content", fail)
        monkeypatch.setattr(phase, "get_response_content", fail)
        monkeypatch.setattr(phase, "get_chat_response_content", fail)

    collapsed, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
    )
    panel._update_family_display(
        root,
        collapsed,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "plan xprompt line 1 · 15 lines" in plain
    assert "plan prompt line 1 · 15 lines" in plain


def test_fully_expanded_family_sections_preserve_full_content(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.FULLY_EXPANDED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.FULLY_EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▼ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 15" in plain
    assert "plan prompt line 15" in plain
    assert "plan reply line 1" in plain
    assert "code reply line 1" in plain


def test_family_section_override_wins_over_collapsed_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, child = _family(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a collapsed section performed a content read")

    monkeypatch.setattr(root, "get_raw_xprompt_content", fail)
    for phase in (root, child):
        monkeypatch.setattr(phase, "get_timestamped_reply_chunks", fail)
        monkeypatch.setattr(phase, "get_live_reply_content", fail)
        monkeypatch.setattr(phase, "get_response_content", fail)
        monkeypatch.setattr(phase, "get_chat_response_content", fail)

    overrides = {FAMILY_PROMPT_SECTION_ID: FoldLevel.FULLY_EXPANDED}
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
        family_section_fold_overrides=overrides,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides=overrides,
    )
    plain = plain_of(panel.captured[-1])

    assert "▸ AGENT XPROMPT\ncontent deferred" in plain
    assert "▼ AGENT PROMPT\n" in plain
    assert "plan prompt line 15" in plain
    assert "▸ AGENT REPLY · 2\n" in plain


def test_family_header_summary_sections_fold_shallowly(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)

    collapsed, _ = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
    )
    expanded, _ = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.EXPANDED,
    )

    assert "▸ OUTPUT VARIABLES · 2\n" in collapsed.plain
    assert "plan_path: /tmp/plan.md" not in collapsed.plain
    assert "▾ OUTPUT VARIABLES · 2\n" in expanded.plain
    assert "plan_path: /tmp/plan.md" in expanded.plain
    assert "code_path: /tmp/code.md" in expanded.plain


def test_family_section_ids_remain_stable() -> None:
    assert FAMILY_XPROMPT_SECTION_ID == "agent-xprompt"
    assert FAMILY_PROMPT_SECTION_ID == "agent-prompt"
    assert FAMILY_REPLY_SECTION_ID == "agent-reply"

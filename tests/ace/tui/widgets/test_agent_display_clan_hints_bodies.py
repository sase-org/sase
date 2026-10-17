"""Clan member-body, workspace, and hint-budget tests."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanDiskSnapshot,
    ClanSectionSnapshot,
    ClanTextEntry,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.util.lazy_syntax import PLAIN_RENDER_MAX_LINES
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._hint_caps import HINT_TRUNCATION_MESSAGE
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent


def _snapshot_with_text(
    container: Agent,
    *,
    replies: tuple[ClanTextEntry, ...] = (),
    prompts: tuple[ClanTextEntry, ...] = (),
) -> ClanSectionSnapshot:
    disk = ClanDiskSnapshot(
        loaded_sections=CLAN_DISK_SECTIONS,
        members=(),
        replies=replies,
        prompts=prompts,
        context_lanes=(),
        slow_tool_calls=(),
    )
    return ClanSectionSnapshot(
        in_memory=aggregate_clan_in_memory(container),
        disk=disk,
    )


def test_clan_level_two_hints_only_rendered_triage_entries(tmp_path: Path) -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.workspace_dir = str(tmp_path)
    container = project_clan_tree([member])[0]
    replies = tuple(
        ClanTextEntry(
            member_identity=member.identity,
            member_label=".one",
            kind="AGENT REPLY",
            preview=f"src/preview-{index}.py",
            body=f"src/full-{index}.py",
        )
        for index in range(10)
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=replies),
        fold_level=FoldLevel.EXPANDED,
    )

    assert len(state.hint_mappings) == 8
    assert list(state.hint_mappings.values()) == [
        str(tmp_path / f"src/preview-{index}.py") for index in range(8)
    ]
    assert "[8] src/preview-7.py" in rendered.plain
    assert "preview-8.py" not in rendered.plain
    assert "+2 more" in rendered.plain
    assert "full-0.py" not in rendered.plain


def test_clan_full_bodies_use_each_members_workspace(tmp_path: Path) -> None:
    started = datetime(2026, 7, 17, 12, 0, 0)
    first = make_clan_agent("research.one", status="RUNNING", start=started)
    second = make_clan_agent(
        "research.two",
        status="RUNNING",
        start=started + timedelta(seconds=1),
    )
    first_workspace = tmp_path / "one"
    second_workspace = tmp_path / "two"
    first_workspace.mkdir()
    second_workspace.mkdir()
    first.workspace_dir = str(first_workspace)
    second.workspace_dir = str(second_workspace)
    container = project_clan_tree([first, second])[0]
    replies = tuple(
        ClanTextEntry(
            member_identity=member.identity,
            member_label=label,
            kind="AGENT REPLY",
            preview="src/shared.py",
            body="Open src/shared.py",
        )
        for member, label in ((first, ".one"), (second, ".two"))
    )
    state = HeaderHintState(1, {}, None, {})

    build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=replies),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert state.hint_mappings == {
        1: str(first_workspace / "src/shared.py"),
        2: str(second_workspace / "src/shared.py"),
    }


def test_clan_member_workspace_is_resolved_lazily_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = make_clan_agent(
        "research.one",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.error_message = "logs/error.txt"
    container = project_clan_tree([member])[0]
    replies = (
        ClanTextEntry(
            member_identity=member.identity,
            member_label=".one",
            kind="AGENT REPLY",
            preview="src/first.py",
            body="src/first.py and src/second.py",
        ),
    )
    resolve_workspace = Mock(return_value="/workspace")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_clan."
        "resolve_agent_workspace_dir",
        resolve_workspace,
    )
    state = HeaderHintState(1, {}, None, {})

    build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=replies),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    resolve_workspace.assert_called_once()


def test_clan_full_sections_hint_values_and_bodies_but_not_variable_names(
    tmp_path: Path,
) -> None:
    member = make_clan_agent(
        "research.one",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.workspace_dir = str(tmp_path)
    member.error_message = "Failure details in logs/error.txt"
    member.error_traceback = 'File "src/crash.py", line 4'
    member.output_variables = {"src/name.py": "data/value.json"}
    member.step_output = {"meta_note": "reports/workflow.md"}
    container = project_clan_tree([member])[0]
    reply = ClanTextEntry(
        member_identity=member.identity,
        member_label=".one",
        kind="AGENT REPLY",
        preview="src/reply.py",
        body="Reply body src/reply.py",
    )
    prompt = ClanTextEntry(
        member_identity=member.identity,
        member_label=".one",
        kind="AGENT PROMPT",
        preview="src/prompt.py",
        body="Prompt body src/prompt.py",
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(
            container,
            replies=(reply,),
            prompts=(prompt,),
        ),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert list(state.hint_mappings.values()) == [
        str(tmp_path / "logs/error.txt"),
        str(tmp_path / "src/crash.py"),
        str(tmp_path / "data/value.json"),
        str(tmp_path / "reports/workflow.md"),
        str(tmp_path / "src/reply.py"),
        str(tmp_path / "src/prompt.py"),
    ]
    assert re.search(r"\[\d+\] src/name\.py", rendered.plain) is None


def test_clan_member_bodies_share_one_hint_budget(tmp_path: Path) -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.workspace_dir = str(tmp_path)
    container = project_clan_tree([member])[0]
    body = "\n".join(
        (
            "src/head.py",
            *(f"filler {index}" for index in range(PLAIN_RENDER_MAX_LINES)),
            "src/tail.py",
        )
    )
    reply = ClanTextEntry(
        member_identity=member.identity,
        member_label=".one",
        kind="AGENT REPLY",
        preview="src/head.py",
        body=body,
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=(reply,)),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert HINT_TRUNCATION_MESSAGE in rendered.plain
    assert state.hint_mappings == {1: str(tmp_path / "src/head.py")}
    assert "src/tail.py" not in rendered.plain

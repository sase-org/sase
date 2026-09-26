"""Session Reply card blocks: one CardBlock per concrete shell."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from rich.console import Group

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_session_members import (
    concrete_agent_session_shell_rows as agent_session_shell_rows,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.util.renderable_digest import renderable_content_digest
from sase.ace.tui.widgets.decks.card_block import (
    BlockSpreadOnly,
    CardBlock,
    card_block_id,
)
from sase.ace.tui.widgets.decks.card_part import CardPart, split_card_parts
from sase.ace.tui.widgets.prompt_panel._agent_display_agent_session import (
    agent_session_roster_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    cache_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    write_phase_content,
)
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of

_STARTED = datetime(2026, 7, 18, 12, 0, 0)
_SUFFIXES = {
    "--plan": "20260718120000",
    "--gate": "20260718120100",
    "--mon": "20260718120200",
    "--code": "20260718120300",
}


def _shell(
    tmp_path: Path,
    role: str,
    suffix: str,
    **overrides: object,
) -> Agent:
    directory = tmp_path / f"shell-{suffix.strip('-')}"
    directory.mkdir(exist_ok=True)
    write_phase_content(directory, role)
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "blocks-test",
        "project_file": "/tmp/blocks.sase",
        "status": "DONE",
        "start_time": _STARTED,
        "raw_suffix": _SUFFIXES[suffix],
        "artifacts_dir": str(directory),
        "response_path": str(directory / "response.md"),
        "agent_name": f"alpha{suffix}",
        "agent_session": "alpha",
        "agent_session_role": role,
        "role_suffix": suffix,
        "model": "claude/opus",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _four_shell_session(tmp_path: Path) -> Agent:
    plan = _shell(tmp_path, "plan", "--plan", plan_chain_root=True)
    gate = _shell(
        tmp_path,
        "gate",
        "--gate",
        status="APPROVE",
        gate_id="g123abc456def",
        gate_kind="approval",
        gate_state="answered",
        gate_start_status="APPROVE",
        gate_stop_status="APPROVED",
        gate_accent="#0BCDEC",
        gate_label="Approve deploy",
    )
    monitor = _shell(
        tmp_path,
        "monitor",
        "--mon",
        status="MONITORED",
        monitor_id="m123abc456def",
        monitor_state="completed",
        monitor_label="just check",
        monitor_command="just check",
    )
    code = _shell(tmp_path, "code", "--code")
    plan.followup_agents = [gate, monitor, code]
    for member in (gate, monitor, code):
        member.agent_session_container = plan
    assert plan.is_agent_session_container_row is True
    assert len(agent_session_shell_rows(plan)) == 4
    return plan


def _render_session(root: Agent) -> object:
    panel = FakePromptPanel()
    header, error = _header_for(panel, root)
    panel._update_agent_session_display(
        root,
        header,
        error,
        panel_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )
    return panel.captured[-1]


def _header_for(panel: FakePromptPanel, root: Agent) -> tuple[object, object]:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
        build_header_text,
    )

    return build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
        lane_section_fold_overrides={},
    )


def _reply_card(renderable: object) -> CardPart:
    cards = split_card_parts(renderable)
    replies = [card for card in cards if card.card_id == "reply"]
    assert len(replies) == 1
    return replies[0]


def test_session_reply_builds_one_block_per_shell(tmp_path: Path) -> None:
    root = _four_shell_session(tmp_path)
    reply = _reply_card(_render_session(root))
    shells = agent_session_shell_rows(root)
    entries = agent_session_roster_entries(root)

    assert [shell.agent_session_role for shell in shells] == [
        "plan",
        "gate",
        "monitor",
        "code",
    ]
    assert reply.block_ids == tuple(card_block_id(shell.identity) for shell in shells)
    assert [block.meta.number for block in reply.blocks] == ["0", "1", "2", "3"]
    assert [block.meta.kind for block in reply.blocks] == [
        "agent",
        "gate",
        "monitor",
        "agent",
    ]
    assert [block.meta.glyph for block in reply.blocks] == ["", "⋔", "⚙", ""]
    assert [block.meta.accent for block in reply.blocks] == [
        "#AF87FF",
        "#0BCDEC",
        "#FFAF5F",
        "#AF87FF",
    ]
    for block, entry in zip(reply.blocks, entries, strict=True):
        assert block.meta.label == entry.label
        assert block.meta.status_bucket == entry.effective_bucket


def test_session_reply_heading_is_block_spread_only(tmp_path: Path) -> None:
    root = _four_shell_session(tmp_path)
    reply = _reply_card(_render_session(root))

    assert len(reply.preamble) == 1
    assert isinstance(reply.preamble[0], BlockSpreadOnly)
    assert "AGENT REPLY · 4" in reply.preamble[0].renderables[0].plain


def test_session_reply_hint_mode_keeps_block_ids_and_hint_order(
    tmp_path: Path,
) -> None:
    root = _four_shell_session(tmp_path)
    plain_renderable = _render_session(root)
    expected_ids = _reply_card(plain_renderable).block_ids

    panel = FakePromptPanel()
    cache_detail_header_summary(panel, root, DetailHeaderSummary())
    panel.update_display_with_hints(root)
    hint_reply = _reply_card(panel.captured[-1])

    assert hint_reply.block_ids == expected_ids
    numbers = [
        int(match) for match in re.findall(r"\[(\d+)\]", plain_of(panel.captured[-1]))
    ]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)


def test_session_reply_plain_text_matches_legacy_modulo_d8(
    tmp_path: Path,
) -> None:
    root = _four_shell_session(tmp_path)
    plain = plain_of(_render_session(root))

    assert "AGENT REPLY · 4\n" in plain
    assert "plan reply line 1" in plain
    assert "code reply line 6" in plain
    # D8: no vestigial blank + rule + blank prefix opens the Reply card.
    lines = plain.splitlines()
    heading = next(
        index for index, line in enumerate(lines) if "AGENT REPLY · 4" in line
    )
    assert lines[heading - 1] != "─" * 50
    assert not (lines[heading - 1] == "" and lines[heading - 2] == "─" * 50)


def test_session_reply_digest_changes_when_shell_status_changes(
    tmp_path: Path,
) -> None:
    root = _four_shell_session(tmp_path)
    before = renderable_content_digest(_render_session(root))

    root.followup_agents[1].monitor_state = "failed"
    after = renderable_content_digest(_render_session(root))

    assert before != after


def test_session_reply_blocks_are_card_blocks(tmp_path: Path) -> None:
    root = _four_shell_session(tmp_path)
    reply = _reply_card(_render_session(root))

    assert all(isinstance(block, CardBlock) for block in reply.blocks)
    assert isinstance(reply.preamble[0], BlockSpreadOnly)
    assert reply.has_block_navigation is True
    assert reply.newest_block_id == reply.block_ids[-1]
    flattened = plain_of(Group(*reply.block_page(reply.newest_block_id)))
    assert "AGENT REPLY · 4" not in flattened

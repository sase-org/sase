"""Legacy followup_agents Reply card blocks: one CardBlock per phase."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from rich.console import Group

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.decks.card_block import (
    BlockSpreadOnly,
    CardBlock,
    card_block_id,
)
from sase.ace.tui.widgets.decks.card_part import CardPart, split_card_parts
from sase.ace.tui.widgets.prompt_panel._agent_display_agent_session import (
    legacy_followup_shell_facts,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
    get_phase_label,
)
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of

_STARTED = datetime(2026, 7, 18, 12, 0, 0)


def _phase_dir(tmp_path: Path, name: str, role: str) -> str:
    directory = tmp_path / name
    directory.mkdir(exist_ok=True)
    (directory / "01_prompt.md").write_text(f"{role} prompt line 1\n", encoding="utf-8")
    (directory / "response.md").write_text(f"{role} reply line 1\n", encoding="utf-8")
    return str(directory)


_RAW_SUFFIXES = {
    "root": "20260718120000",
    "followup": "20260718120100",
    "monitor": "20260718120200",
    "gate": "20260718120300",
}


def _plain_phase(
    tmp_path: Path, name: str, role: str, suffix: str, **overrides: object
) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "legacy-blocks-test",
        "project_file": "/tmp/legacy-blocks.sase",
        "status": "DONE",
        "start_time": _STARTED,
        "run_start_time": _STARTED,
        "raw_suffix": _RAW_SUFFIXES[name],
        "artifacts_dir": _phase_dir(tmp_path, name, role),
        "response_path": str(tmp_path / name / "response.md"),
        "agent_name": f"legacy-{name}",
        "role_suffix": suffix,
        "model": "claude/opus",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _legacy_root(tmp_path: Path) -> Agent:
    root = _plain_phase(tmp_path, "root", "root", "--code")
    followup = _plain_phase(tmp_path, "followup", "followup", "--code-0")
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir(exist_ok=True)
    (monitor_dir / "live_reply.md").write_text(
        "monitor output line\n", encoding="utf-8"
    )
    monitor = _plain_phase(
        tmp_path,
        "monitor",
        "monitor",
        "--mon",
        status="MONITORED",
        agent_name="legacy-monitor",
        agent_session_role="monitor",
        artifacts_dir=str(monitor_dir),
        monitor_id="m123abc456def",
        monitor_state="completed",
        monitor_label="just check",
        monitor_command="just check",
    )
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir(exist_ok=True)
    (gate_dir / "live_reply.md").write_text("gate output line\n", encoding="utf-8")
    gate = _plain_phase(
        tmp_path,
        "gate",
        "gate",
        "--gate",
        status="APPROVE",
        agent_name="legacy-gate",
        agent_session_role="gate",
        artifacts_dir=str(gate_dir),
        gate_id="g123abc456def",
        gate_kind="approval",
        gate_state="answered",
        gate_start_status="APPROVE",
        gate_stop_status="APPROVED",
        gate_accent="#0BCDEC",
        gate_label="Approve deploy",
    )
    root.followup_agents = [followup, monitor, gate]
    assert root.is_agent_session_container_row is False
    return root


def _render_legacy(root: Agent) -> object:
    panel = FakePromptPanel()
    panel.update_display(root)
    return panel.captured[-1]


def _reply_card(renderable: object) -> CardPart:
    cards = split_card_parts(renderable)
    replies = [card for card in cards if card.card_id == "reply"]
    assert len(replies) == 1
    return replies[0]


def test_legacy_reply_builds_one_block_per_phase(tmp_path: Path) -> None:
    root = _legacy_root(tmp_path)
    reply = _reply_card(_render_legacy(root))
    phases = (root, *root.followup_agents)

    assert reply.block_ids == tuple(card_block_id(phase.identity) for phase in phases)
    assert [block.meta.number for block in reply.blocks] == ["0", "1", "2", "3"]
    assert [block.meta.kind for block in reply.blocks] == [
        "agent",
        "agent",
        "monitor",
        "gate",
    ]
    assert [block.meta.glyph for block in reply.blocks] == ["", "", "⚙", "⋔"]
    for block, phase in zip(reply.blocks, phases, strict=True):
        assert block.meta.label == get_phase_label(phase)
    assert all(isinstance(block, CardBlock) for block in reply.blocks)


def test_legacy_reply_heading_is_block_spread_only(tmp_path: Path) -> None:
    root = _legacy_root(tmp_path)
    reply = _reply_card(_render_legacy(root))

    assert len(reply.preamble) == 1
    assert isinstance(reply.preamble[0], BlockSpreadOnly)
    assert "AGENT REPLY · 4" in reply.preamble[0].renderables[0].plain


def test_legacy_reply_plain_text_keeps_every_phase(tmp_path: Path) -> None:
    root = _legacy_root(tmp_path)
    plain = plain_of(_render_legacy(root))

    assert "AGENT REPLY · 4" in plain
    assert "root reply line 1" in plain
    assert "followup reply line 1" in plain
    assert "MONITOR" in plain
    assert "Approve deploy" in plain


def test_legacy_followup_shell_facts_use_role_suffix_labels(
    tmp_path: Path,
) -> None:
    root = _legacy_root(tmp_path)
    facts = legacy_followup_shell_facts(root)
    phases = (root, *root.followup_agents)

    assert [fact.member.identity for fact in facts] == [
        phase.identity for phase in phases
    ]
    assert [fact.label for fact in facts] == [
        get_phase_label(phase) for phase in phases
    ]
    assert [fact.kind for fact in facts] == ["agent", "agent", "monitor", "gate"]


def test_legacy_reply_hint_mode_keeps_block_ids(tmp_path: Path) -> None:
    root = _legacy_root(tmp_path)
    expected_ids = _reply_card(_render_legacy(root)).block_ids

    panel = FakePromptPanel()
    panel.update_display_with_hints(root)
    hint_reply = _reply_card(panel.captured[-1])

    assert hint_reply.block_ids == expected_ids
    assert len(hint_reply.preamble) == 1
    assert isinstance(hint_reply.preamble[0], BlockSpreadOnly)


def test_legacy_reply_hint_mode_renders_gate_phase(tmp_path: Path) -> None:
    root = _legacy_root(tmp_path)

    panel = FakePromptPanel()
    panel.update_display_with_hints(root)
    plain = plain_of(panel.captured[-1])

    assert "AGENT REPLY · 4" in plain
    assert "Approve deploy" in plain
    assert "MONITOR" in plain
    numbers = [int(match) for match in re.findall(r"\[(\d+)\]", plain)]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)


def test_legacy_reply_block_page_hides_heading(tmp_path: Path) -> None:
    root = _legacy_root(tmp_path)
    reply = _reply_card(_render_legacy(root))

    assert reply.has_block_navigation is True
    assert reply.newest_block_id == reply.block_ids[-1]
    flattened = plain_of(Group(*reply.block_page(reply.newest_block_id)))
    assert "AGENT REPLY · 4" not in flattened

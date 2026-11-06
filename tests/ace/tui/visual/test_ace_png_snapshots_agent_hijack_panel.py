"""80×24 PNG snapshots for the Agent Hijack recovery panel."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from xml.etree import ElementTree

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._hijack_recovery_panel import (
    _apply_preview,
    _header_from_record,
    _initial_choices,
    _preview_header,
    _title_badge,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.agent_action_chooser_modal import AgentActionChooserModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import wait_for_visual_idle
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _svg_text(page: Any) -> str:
    root = ElementTree.fromstring(page.export_svg(title="recovery panel assertion"))
    return "\n".join(
        "".join(element.itertext())
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "text"
    ).replace("\xa0", " ")


def _record(*, state: str = "held") -> dict[str, Any]:
    return {
        "hijack_id": "visual-hijack-1",
        "agent_name": "visual-recovery",
        "artifacts_dir": "/workspace/artifacts/visual-recovery",
        "revision": 3,
        "state": state,
        "workspace_num": 4,
        "workspace_dir": "/workspace/project_4",
        "model_alias": "large",
        "provider": "claude",
        "model": "opus",
        "effort": "high",
        "run_duration_seconds": 2820,
        "last_tool": "Bash just check",
        "last_tool_age_seconds": 1320,
        "repo_diffs": [
            {
                "repo": "/workspace/project_4",
                "files_changed": 5,
                "insertions": 212,
                "deletions": 31,
            }
        ],
        "snapshots": [{"repo": "/workspace/project_4", "reference": "snapshot-visual"}],
    }


def _agent(record: dict[str, Any], *, name: str = "visual-recovery") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-recovery",
        project_file="/workspace/project.sase",
        status="HIJACKED",
        start_time=datetime(2026, 11, 3, 10, 0, 0),
        workspace_num=4,
        workspace_dir="/workspace/project_4",
        raw_suffix="20261103100000",
        agent_name=name,
        llm_provider="claude",
        model="opus",
        hijack_id="visual-hijack-1",
        hijack_record=record,
        hijack_expired=record["state"] == "expired",
    )


def _preview(*, switch: bool = False, restart_disabled: bool = False) -> Any:
    actions = {
        "escalate": SimpleNamespace(
            label="Switch" if switch else "Escalate",
            detail="already @xlarge" if switch else "@large → @xlarge",
            target="codex/gpt-6.1-sol@xhigh" if switch else "claude/opus@xhigh",
            available=True,
            reason=None,
        ),
        "continue": SimpleNamespace(
            label="Continue",
            detail="same model",
            target="claude/opus@high",
            available=True,
            reason=None,
        ),
        "restart": SimpleNamespace(
            label="Restart",
            detail="same prompt, same name, fresh workspace",
            target=None,
            available=not restart_disabled,
            reason=(
                "unavailable: fan-out prompt; use Edit" if restart_disabled else None
            ),
        ),
        "edit": SimpleNamespace(
            label="Edit",
            detail="edit the prompt; nothing is released until submit",
            target=None,
            available=True,
            reason=None,
        ),
    }
    return SimpleNamespace(
        state="held",
        actions=tuple(actions.values()),
        action=lambda name: actions.get(name),
        header={
            "model_display": "claude/opus@high",
            "run_duration_display": "47m",
            "hijacked_ago": "3m ago",
            "files_changed": 5,
            "insertions": 212,
            "deletions": 31,
            "last_tool": "Bash just check",
            "last_tool_age": "22m",
        },
    )


async def _capture_panel(
    ace_png_visual: AcePngSnapshotFixture,
    *,
    snapshot_name: str,
    record: dict[str, Any],
    resolved: bool,
    switch: bool = False,
    restart_disabled: bool = False,
    long_name: bool = False,
) -> None:
    name = (
        "visual-recovery-" + "very-long-agent-name-that-needs-ellipsis-in-the-title"
        if long_name
        else "visual-recovery"
    )
    agent = _agent(record, name=name)
    app = SimpleNamespace(_resolve_agent_cl_name=lambda _agent: "visual-recovery")
    choices = _initial_choices(app, agent, record)
    header = _header_from_record(record)
    primary = (
        "hijack:escalate" if any(c.result == "hijack:escalate" for c in choices) else ""
    )
    if resolved:
        preview = _preview(switch=switch, restart_disabled=restart_disabled)
        choices = _apply_preview(choices, preview)
        header = _preview_header(preview.header, record)
        if record["state"] == "expired":
            primary = ""
    modal = AgentActionChooserModal(
        choices,
        title=f"⏏ Recover {name}",
        title_badge=_title_badge(agent, record),
        header=header,
        section_subtitles={
            "hijack_keep": "next turn runs in workspace #4",
        },
        primary_result=primary,
        initial_index=0,
        arm_delay_seconds=0.3,
        footer_text="j/k move · ⏎ select · Esc decide later",
    )
    if resolved:
        preferred = (
            "hijack:continue"
            if switch and restart_disabled
            else ("" if record["state"] == "expired" else "hijack:escalate")
        )
        modal.update_choices(choices, primary_result=primary, selected_result=preferred)
    async with AcePage(size=(80, 24)) as page:
        page.app.push_screen(modal, lambda _result: None)
        await page.expect_modal("AgentActionChooserModal")
        visible_section = (
            "START OVER" if record["state"] == "expired" else "KEEP THE WORK"
        )
        await page.wait_for(lambda _screen: visible_section in _svg_text(page))
        await wait_for_visual_idle(page)
        visible_text = _svg_text(page)
        assert "PATCH" in visible_text
        assert "j/k move" in visible_text
        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=f"Agent Hijack recovery panel · {snapshot_name}",
        )


async def test_agent_hijack_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
) -> None:
    await _capture_panel(
        ace_png_visual,
        snapshot_name="agent_hijack_panel_80x24",
        record=_record(),
        resolved=True,
    )


async def test_agent_hijack_panel_switch_disabled_restart_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
) -> None:
    await _capture_panel(
        ace_png_visual,
        snapshot_name="agent_hijack_panel_switch_disabled_restart_80x24",
        record=_record(),
        resolved=True,
        switch=True,
        restart_disabled=True,
    )


async def test_agent_hijack_panel_pending_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
) -> None:
    await _capture_panel(
        ace_png_visual,
        snapshot_name="agent_hijack_panel_pending_80x24",
        record=_record(),
        resolved=False,
    )


async def test_agent_hijack_panel_expired_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
) -> None:
    await _capture_panel(
        ace_png_visual,
        snapshot_name="agent_hijack_panel_expired_80x24",
        record=_record(state="expired"),
        resolved=True,
    )


async def test_agent_hijack_panel_long_name_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
) -> None:
    await _capture_panel(
        ace_png_visual,
        snapshot_name="agent_hijack_panel_long_name_80x24",
        record=_record(),
        resolved=True,
        long_name=True,
    )


_INSTRUCT_BAR_TEXT = (
    "%model:claude/opus@high\n"
    "#fork:visual-recovery\n"
    "\n"
    "**Hijack continuation.** The user stopped `visual-recovery` "
    "(`claude/opus@high`) because it stopped making progress. "
    "Inspect `git status` and `git diff` before acting.\n"
    "\n"
    "Do the task.\n"
)


async def test_agent_hijack_instruct_bar_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: Any,
) -> None:
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
    from tests.ace.tui.visual._ace_png_snapshot_helpers import (
        patches,
        patch_startup_loaders,
        wait_for_startup,
        wait_for_state,
    )

    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches(), size=(80, 24)) as page:
        await wait_for_startup(page)
        await page.app.mount(
            PromptInputBar(
                initial_value=_INSTRUCT_BAR_TEXT,
                initial_cursor=(2, 0),
                id="prompt-input-bar",
            )
        )
        bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
        await wait_for_state(
            page,
            lambda: bar.active_text_area().has_focus,
            description="instruct-bar focus",
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agent_hijack_instruct_bar_80x24",
            title="Agent Hijack pre-filled Instruct bar",
        )

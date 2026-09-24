"""Shared harness for agent jump-panel widget tests."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult

from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_jump_panel import AgentJumpPanel
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _solo() -> Any:
    return make_agent(agent_name="solo")


class _DetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _show_agent(detail: AgentDetail, agent: Any, pilot: Any) -> None:
    detail.update_display_immediate(agent)
    await pilot.pause()


def _jump_panel(detail: AgentDetail) -> AgentJumpPanel:
    return detail.query_one("#agent-jump-panel", AgentJumpPanel)


def _jump_text(panel: AgentJumpPanel) -> str:
    content = panel.query_one("#agent-jump-content")
    return renderable_to_text(getattr(content, "content", None)) or ""


def _labeled_map(
    container: Any,
    labels: list[str],
    *,
    roles: list[str] | None = None,
    title: str = "ROSTER",
    accent: str = "#00D7AF",
) -> MemberJumpMap:
    """Build a labeled jump map over synthetic roster entries."""
    entries = tuple(
        MemberRosterEntry(
            identity=(container.identity[0], label, None),
            presented_name=label,
            label=label,
            kind="agent",
            status="RUNNING",
            model="m",
            duration="1m",
            is_dismissed=(role == "dismissed"),
            target_role=role if role != "member" else None,  # type: ignore[arg-type]
        )
        for label, role in zip(labels, roles or ["member"] * len(labels), strict=True)
    )
    return append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title=title,
        accent=accent,
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )


def _labeled_map_and_roster(
    container: Any,
    labels: list[str],
    *,
    roles: list[str] | None = None,
    title: str = "ROSTER",
    accent: str = "#00D7AF",
) -> tuple[MemberJumpMap, Text | None]:
    """Build a labeled jump map plus its detached roster text."""
    from sase.ace.tui.widgets.prompt_panel._member_roster import (
        detached_roster_text,
    )

    entries = tuple(
        MemberRosterEntry(
            identity=(container.identity[0], label, None),
            presented_name=label,
            label=label,
            kind="agent",
            status="RUNNING",
            model="m",
            duration="1m",
            is_dismissed=(role == "dismissed"),
            target_role=role if role != "member" else None,  # type: ignore[arg-type]
        )
        for label, role in zip(labels, roles or ["member"] * len(labels), strict=True)
    )
    text = Text()
    jump_map = append_member_roster(
        text,
        container_identity=container.identity,
        entries=entries,
        title=title,
        accent=accent,
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    return jump_map, detached_roster_text(text)

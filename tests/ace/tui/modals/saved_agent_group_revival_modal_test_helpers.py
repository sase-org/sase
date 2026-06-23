"""Shared helpers for saved agent group revival modal tests."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import App
from textual.widgets import Static
from textual.widgets.option_list import Option

from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalResult,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)


class _TestApp(App[SavedAgentGroupRevivalResult | None]):
    pass


def _summary(idx: int, *, name: str | None = None) -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id=f"group-{idx:02}",
        created_at=f"2026-05-27T12:{idx % 60:02}:00Z",
        source="marked_agents",
        title="3 agents from backend",
        name=name,
        agent_count=3,
        top_level_agent_count=2,
        status_counts={"DONE": 2, "FAILED": 1},
        project_names=("sase",),
        cl_names=("backend",),
    )


def _recent_summary() -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id="recent-00",
        created_at="2026-05-27T12:10:00Z",
        source="recent_dismissal",
        title="1 agent in backend",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("sase",),
        cl_names=("backend",),
    )


def _group(group_id: str) -> SavedAgentGroupWire:
    return SavedAgentGroupWire(
        group_id=group_id,
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="3 agents from backend",
        agent_count=3,
        top_level_agent_count=2,
        status_counts={"DONE": 2, "FAILED": 1},
        project_names=("sase",),
        cl_names=("backend",),
        agent_refs=(
            SavedAgentGroupRefWire(
                agent_type="run",
                cl_name="backend",
                raw_suffix="20260527120000",
                display_name="worker-one",
                agent_name="backend.1",
                status="DONE",
                model="gpt-5",
                llm_provider="codex",
                prompt_preview="Restore this backend worker.",
            ),
        ),
    )


def _static_plain(static: Static) -> str:
    renderable = static.content
    plain = getattr(renderable, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(renderable)


def _option_plain(option: Option) -> str:
    prompt = option.prompt
    plain = getattr(prompt, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(prompt)


@dataclass
class _FakeKeyEvent:
    """Minimal stand-in for a Textual key event in jump-mode tests."""

    key: str
    character: str | None
    prevented: bool = False
    stopped: bool = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True

"""Shared data models and display styles for agent completion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.agent_family_plan_preview import AgentFamilyPlanPreview


@dataclass(frozen=True, slots=True)
class AgentVcsWorkflow:
    """Display metadata for the VCS workflow tag used by an agent prompt."""

    tag: str
    workflow_type: str | None
    project: str | None
    provider_display: str | None
    style: str

    @property
    def display(self) -> str:
        return self.tag or "local"


@dataclass(frozen=True, slots=True)
class AgentCompletionCandidate:
    """A visible prompt target that can be inserted into prompt syntax."""

    name: str
    label: str
    status: str
    runtime: str | None = None
    model: str | None = None
    start_time: str | None = None
    duration: str | None = None
    role: str | None = None
    tribe: str | None = None
    vcs_workflow: AgentVcsWorkflow | None = None
    plan_preview: AgentFamilyPlanPreview | None = None
    prompt_snippet: str = ""
    search_aliases: tuple[str, ...] = ()
    kind: Literal["agent", "family", "clan", "tribe"] = "agent"
    member_count: int | None = None
    aggregate_status: str | None = None
    member_names: tuple[str, ...] = ()
    agent_count: int | None = None
    clan_count: int | None = None

    @property
    def wait_name(self) -> str:
        """Compatibility label used by the wait modal."""
        return self.name

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.name,
                self.label,
                self.prompt_snippet,
                (
                    self.plan_preview.title or ""
                    if self.plan_preview is not None
                    else ""
                ),
                *self.member_names,
                *self.search_aliases,
            )
        ).lower()


def status_style(status: str) -> str:
    """Return the Rich style used for a status indicator."""
    status_upper = status.upper()
    if status_upper in {"RUNNING", "STARTING"}:
        return "bold #00D7AF"
    if status_upper == "QUEUED":
        return "bold #5F87FF"
    if status_upper == "WAITING":
        return "bold #AF87FF"
    if "DONE" in status_upper:
        return "bold #5FD7FF"
    if "FAILED" in status_upper:
        return "bold #FF5F5F"
    return "dim"


def neutral_vcs_workflow() -> AgentVcsWorkflow:
    """Return the neutral local workflow marker for rows without a VCS tag."""
    return AgentVcsWorkflow(
        tag="local",
        workflow_type=None,
        project=None,
        provider_display=None,
        style="dim",
    )


__all__ = [
    "AgentCompletionCandidate",
    "AgentVcsWorkflow",
    "neutral_vcs_workflow",
    "status_style",
]

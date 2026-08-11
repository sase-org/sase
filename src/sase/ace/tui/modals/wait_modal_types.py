"""Data models shared by the wait modal modules."""

from __future__ import annotations

from dataclasses import dataclass, field

from sase.ace.tui.agent_completion import AgentVcsWorkflow


@dataclass(frozen=True)
class WaitAgentCandidate:
    """Display metadata for an agent that can be selected as a wait target."""

    wait_name: str
    label: str
    status: str
    runtime: str | None = None
    model: str | None = None
    start_time: str | None = None
    duration: str | None = None
    role: str | None = None
    tribe: str | None = None
    vcs_workflow: AgentVcsWorkflow | None = None
    prompt_snippet: str = ""

    @property
    def search_text(self) -> str:
        return " ".join((self.wait_name, self.label, self.prompt_snippet)).lower()


@dataclass(frozen=True)
class WaitModalResult:
    """Structured result returned by :class:`WaitModal`."""

    agents: list[str]
    time_token: str | None
    runners: int | None = None
    priority: int | None = None
    update_priority: bool = False
    beads: list[str] = field(default_factory=list)
    run_now: bool = False


__all__ = ["WaitAgentCandidate", "WaitModalResult"]

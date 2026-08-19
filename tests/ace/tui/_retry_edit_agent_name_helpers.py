"""Shared helpers for Agents-tab retry-edit / kill-and-edit name tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sase.ace.tui.actions.agent_workflow._entry_points import EntryPointsMixin
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)


_EPIC_ROOT_PROMPT = (
    "#gh:gh_sase-org__sase\n"
    "%id(sase-pw.1, bead=sase-pw.1)\n"
    "%clan(sase-pw, tribe=epic, summary_script=sase_clan_summary_epic)\n"
    "%model:@medium\n"
    "%auto\n"
    "#bd/work_phase_bead:sase-pw.1"
)
_EPIC_ROOT_RELAUNCH = (
    "%id(!1, clan=sase-pw, bead=sase-pw.1)\n"
    "#gh:gh_sase-org__sase\n"
    "%model:@medium\n"
    "%auto\n"
    "#bd/work_phase_bead:sase-pw.1"
)


@pytest.fixture(autouse=True)
def _configured_machine_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


@dataclass
class _Agent:
    raw_prompt: str | None
    agent_name: str | None = "foo"
    project_file: str = "/tmp/proj/proj.sase"
    cl_name: str = "branch"
    is_project_agent: bool = False
    status: str = "DONE"
    pid: int | None = None
    workspace_num: int | None = None
    agent_family: str | None = None
    agent_family_parallel: bool = False
    role_suffix: str | None = None
    phase_bead_id: str | None = None
    is_family_root_entry: bool = False
    is_clan_container: bool = False

    def get_raw_xprompt_content(self) -> str | None:
        return self.raw_prompt


class _App(EntryPointsMixin):
    def __init__(self, agent: _Agent) -> None:
        self.agent = agent
        self.launched: tuple[str, str, str, bool] | None = None
        self.notifications: list[tuple[str, str | None]] = []

    def _get_selected_agent(self) -> _Agent:
        return self.agent

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.launched = (raw_prompt, project_file, cl_name, is_project_agent)

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _dismiss_done_agent(self, agent: _Agent) -> None:
        return None

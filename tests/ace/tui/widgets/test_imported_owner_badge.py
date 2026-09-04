"""Owner badges for imported agents on rows, detail, and neighbor roster."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.modals.agent_neighbor_modal import (
    AgentNeighborChoice,
    _agent_neighbor_option_text,
)
from sase.ace.tui.modals.revive_agent_rendering import (
    build_metadata_preview,
    format_agent_label,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_owner_badge import agent_owner_badge_label
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_header_metadata import (
    _append_identity_fields,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from rich.text import Text
import pytest


def _imported_agent(*, owner: AgentOwnerIdentity, name: str) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 7, 24, 12, 0, 0),
        raw_suffix="20260724120000",
        agent_name=name,
        imported_source_owner=owner,
    )
    agent.presented_agent_name = name
    return agent


@pytest.fixture
def local_owner(monkeypatch: pytest.MonkeyPatch) -> AgentOwnerIdentity:
    owner = AgentOwnerIdentity("alice", "kellys_mbp")
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(
            lambda cls: AgentIdentitySnapshot(
                owner, ("kellys_mbp", "athena"), ("kellys_mbp", "athena")
            )
        ),
    )
    return owner


def test_owner_badge_label_for_foreign_machine_and_foreign_user(
    local_owner: AgentOwnerIdentity,
) -> None:
    foreign_machine = _imported_agent(
        owner=AgentOwnerIdentity("alice", "athena"),
        name="athena.7n--code",
    )
    foreign_user = _imported_agent(
        owner=AgentOwnerIdentity("bob", "zeus"),
        name="bob.zeus.crew--code",
    )
    assert agent_owner_badge_label(foreign_machine) == "athena"
    assert agent_owner_badge_label(foreign_user) == "bob@zeus"


def test_agent_row_renders_owner_badge(local_owner: AgentOwnerIdentity) -> None:
    agent = _imported_agent(
        owner=AgentOwnerIdentity("alice", "athena"),
        name="athena.7n--code",
    )
    agent.presented_agent_name = "7n--code"
    left, _, _ = format_agent_option(agent, 0, is_selected=False)
    assert "7n--code" in left.plain
    assert "[athena]" in left.plain


def test_detail_header_renders_owner_field(local_owner: AgentOwnerIdentity) -> None:
    agent = _imported_agent(
        owner=AgentOwnerIdentity("bob", "zeus"),
        name="bob.zeus.crew--code",
    )
    agent.presented_agent_name = "crew--code"
    text = Text()
    _append_identity_fields(text, agent, None, lambda _agent: None, None)
    assert "Owner:" in text.plain
    assert "bob@zeus" in text.plain


def test_neighbor_roster_renders_owner_badge() -> None:
    choice = AgentNeighborChoice(
        agent_name="7n--code",
        display_name="7n--code",
        status="DONE",
        panel_label="@backend",
        owner_badge="athena",
    )
    rendered = _agent_neighbor_option_text("a", choice)
    assert "[athena]" in rendered.plain


def test_revival_label_and_preview_render_owner_badge(
    local_owner: AgentOwnerIdentity,
) -> None:
    agent = _imported_agent(
        owner=AgentOwnerIdentity("bob", "zeus"),
        name="bob.zeus.crew--plan",
    )
    agent.presented_agent_name = "crew--plan"
    label = format_agent_label(agent, 0)
    preview = build_metadata_preview(agent, [])
    assert "[bob@zeus]" in label.plain
    assert "Owner" in preview.plain
    assert "bob@zeus" in preview.plain

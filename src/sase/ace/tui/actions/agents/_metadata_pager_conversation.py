"""Adapt the detail panel's conversation loaders into navigable pager sections.

Call only from the metadata document worker: the existing panel loaders do
cached disk I/O. Each lane can fail independently of metadata and other lanes.
"""

from __future__ import annotations

import json
from typing import cast

from rich.console import Group, RenderableType
from rich.text import Text

from sase.pager.document import PagerSection, RawSourceSpec
from sase.pager.link_context import agent_link_context
from sase.pager.owner import document_owner_from_path

from ...models._agent_clan_sections import ClanDiskSection, clan_section_member_rows
from ...models.agent import Agent
from ...models.agent_family_members import concrete_family_shell_rows
from ...widgets.prompt_panel._agent_clan_member_content import (
    load_clan_disk_member_snapshot,
)
from ...widgets.prompt_panel._agent_gate_section import build_gate_phase
from ...widgets.prompt_panel._agent_monitor_section import build_monitor_phase

_CONVERSATION_SECTIONS = (
    ("xprompt", "AGENT XPROMPT", "No original xprompt available."),
    ("prompt", "AGENT PROMPT", "No expanded prompt available."),
    ("reply", "AGENT REPLY", "No reply content available. Press r to refresh."),
)


def build_agent_conversation_sections(agent: Agent) -> tuple[PagerSection, ...]:
    """Show each concrete member's conversation in the panel's member order."""
    if agent.is_clan_container:
        members = clan_section_member_rows(agent)
    elif agent.followup_agents:
        members = concrete_family_shell_rows(agent)
    else:
        members = (agent,)
    attributed = agent.is_clan_container or bool(agent.followup_agents)
    sections: list[PagerSection] = []
    for member in members:
        label = (
            member.presented_identity_name or member.agent_name or member.display_name
        )
        # Use the persisted row identity, never the position, name, or reply source.
        # Appending a family member or switching live reply to chat keeps r anchored.
        prefix = f"agent-conversation:{json.dumps(member.identity, default=str)}"
        context = agent_link_context(
            member.effective_workspace_num, member.project_file, member.workspace_dir
        )
        owner = (
            document_owner_from_path(member.workspace_dir)
            if member.workspace_dir
            else None
        )
        suffix = f" · {label}" if attributed else ""
        if member.is_monitor or member.is_gate:
            title = "MONITOR" if member.is_monitor else "GATE"
            build_phase = build_monitor_phase if member.is_monitor else build_gate_phase
            sections.append(
                PagerSection(
                    identity=f"{prefix}-output",
                    title=title + suffix,
                    kind="agent",
                    body=Group(*cast(list[RenderableType], build_phase(member))),
                    link_anchors=context.anchors,
                    owner=owner,
                )
            )
            continue

        bodies: dict[str, str] = {}
        errors: dict[str, str] = {}
        reply_title = "AGENT REPLY"
        lanes: tuple[ClanDiskSection, ...] = ("prompts", "replies")
        for lane in lanes:
            try:
                snapshot = load_clan_disk_member_snapshot(
                    member, label, frozenset({lane})
                )
            except (OSError, UnicodeError) as exc:
                affected = ("xprompt", "prompt") if lane == "prompts" else ("reply",)
                for key in affected:
                    errors[key] = f"Could not load {lane}: {exc}. Press r to retry."
                continue
            for entry in snapshot.prompts:
                key = "xprompt" if entry.kind == "AGENT XPROMPT" else "prompt"
                bodies[key] = entry.body
            for entry in snapshot.replies:
                bodies["reply"] = entry.body
                if entry.kind == "STEP OUTPUT":
                    reply_title = entry.kind

        for key, title, empty_message in _CONVERSATION_SECTIONS:
            body = bodies.get(key)
            sections.append(
                PagerSection(
                    identity=f"{prefix}-{key}",
                    title=(reply_title if key == "reply" else title) + suffix,
                    kind="agent",
                    body=body
                    if body
                    else Text(
                        errors.get(key, empty_message),
                        style="italic yellow" if key in errors else "dim italic",
                    ),
                    raw_source=RawSourceSpec(language="markdown") if body else None,
                    link_anchors=context.anchors,
                    owner=owner,
                )
            )
    return tuple(sections)

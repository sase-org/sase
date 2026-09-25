"""Thread-only Tier 1 content loader for the Node Finder preview."""

from __future__ import annotations

from collections import OrderedDict
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text

from sase.procs.text_bounding import tail_text_by_lines_and_chars

from ..models._projected_record import (
    hydrate_projected_agent,
    projected_agent_waiting_for_hydration,
)
from ..models.agent import AgentType
from ..models.node_finder import NodeFinderRole, NodeFinderRow, NodeFinderSnapshot
from ..widgets.prompt_panel._agent_display_content import get_prompt_content

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.node_finder import AgentIdentity


type PreviewToken = tuple[tuple[str, int | None, int | None], ...]
_CACHE_CAPACITY = 128


@dataclass(frozen=True, slots=True)
class NodeFinderPreviewPayload:
    """Bounded worker result and the source-file freshness token."""

    identity: AgentIdentity
    source_name: str
    prompt: str
    reply: str
    reply_omitted_lines: int
    reply_omitted_chars: int
    token: PreviewToken


class NodeFinderPreviewCache:
    """Modal-local LRU cache of Tier 1 preview results."""

    def __init__(self, capacity: int = _CACHE_CAPACITY) -> None:
        self._capacity = max(1, capacity)
        self._entries: OrderedDict[AgentIdentity, NodeFinderPreviewPayload] = (
            OrderedDict()
        )

    def get(self, identity: AgentIdentity) -> NodeFinderPreviewPayload | None:
        """Return a cached payload and make it the most recently used entry."""

        payload = self._entries.get(identity)
        if payload is not None:
            self._entries.move_to_end(identity)
        return payload

    def put(self, payload: NodeFinderPreviewPayload) -> None:
        """Store *payload*, evicting the least recently used result if needed."""

        self._entries[payload.identity] = payload
        self._entries.move_to_end(payload.identity)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def is_fresh(self, payload: NodeFinderPreviewPayload, agent: Agent) -> bool:
        """Return whether the worker-visible source token still matches."""

        return payload.token == node_finder_preview_token(agent)


def tier1_source(row: NodeFinderRow, snapshot: NodeFinderSnapshot) -> Agent | None:
    """Return the artifact-backed agent represented by one Finder row.

    Session containers use their newest regular agent-shell member.  The
    snapshot parameter keeps this API parallel with Tier 0 even though session
    membership is already represented on the container's loaded row.
    """

    del snapshot
    if row.role is not NodeFinderRole.NODE or row.agent is None:
        return None
    agent = row.agent
    if (
        agent.is_clan_container
        or agent.is_monitor
        or agent.is_gate
        or agent.is_proc_shell
    ):
        return None
    if agent.is_agent_session_container_row:
        shells = [member for member in agent.followup_agents if _is_agent_shell(member)]
        if not shells:
            return None
        return max(shells, key=_newest_shell_key)
    return agent if _is_agent_shell(agent) else None


def load_node_finder_preview(agent: Agent) -> NodeFinderPreviewPayload:
    """Read bounded prompt/reply content from a worker thread only.

    A shallow copy is hydrated and read so neither projected-record hydration
    nor artifact cache details can alter the live Agents-tab row.
    """

    source = copy(agent)
    if projected_agent_waiting_for_hydration(source):
        hydrate_projected_agent(source)
    prompt = _head_text(get_prompt_content(source) or "", max_lines=8, max_chars=2_048)
    reply_raw = _reply_content(source)
    reply_tail = tail_text_by_lines_and_chars(reply_raw, 20, 8_192)
    return NodeFinderPreviewPayload(
        identity=agent.identity,
        source_name=_source_name(source),
        prompt=prompt,
        reply=reply_tail.text,
        reply_omitted_lines=reply_tail.omitted_lines,
        reply_omitted_chars=reply_tail.omitted_chars,
        token=node_finder_preview_token(source),
    )


def node_finder_preview_token(agent: Agent) -> PreviewToken:
    """Return worker-side mtime/size facts for relevant artifact sources."""

    return tuple(_path_token(path) for path in _source_paths(agent))


def render_tier1(payload: NodeFinderPreviewPayload) -> Text:
    """Render a loaded Tier 1 payload as plain, soft-colored text."""

    text = Text()
    _append_section_header(text, _prompt_label(payload), "#87D7FF")
    text.append(payload.prompt or "(no prompt recorded)", style="#87D7FF")
    text.append("\n")
    _append_section_header(text, "REPLY · tail", "#D7D7FF")
    if payload.reply_omitted_lines:
        text.append(f"… {payload.reply_omitted_lines} earlier lines\n", style="dim")
    text.append(payload.reply or "(no reply recorded)")
    return text


def _is_agent_shell(agent: Agent) -> bool:
    return agent.is_agent_entry


def _newest_shell_key(agent: Agent) -> tuple[object, str]:
    return (
        agent.run_start_time or agent.start_time or 0,
        agent.presented_agent_name or agent.agent_name or "",
    )


def _source_name(agent: Agent) -> str:
    return agent.presented_agent_name or agent.agent_name or agent.display_name


def _head_text(text: str, *, max_lines: int, max_chars: int) -> str:
    """Bound prompt text from the front without splitting its final line."""

    kept: list[str] = []
    remaining = max_chars
    for line in text.splitlines():
        if len(kept) >= max_lines or remaining <= 0:
            break
        segment = line[:remaining]
        kept.append(segment)
        remaining -= len(segment) + 1
        if len(segment) != len(line):
            break
    return "\n".join(kept)


def _reply_content(agent: Agent) -> str:
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        return "\n".join(content.strip() for _, content in chunks if content.strip())
    return (
        agent.get_live_reply_content()
        or agent.get_response_content()
        or agent.get_chat_response_content()
        or ""
    )


def _source_paths(agent: Agent) -> tuple[str, ...]:
    paths: list[str] = []
    try:
        artifacts_dir = agent.get_artifacts_dir()
    except (AttributeError, OSError, ValueError):
        artifacts_dir = None
    if artifacts_dir:
        paths.extend(
            str(Path(artifacts_dir) / name)
            for name in (
                "live_reply.md",
                "live_reply_timestamps.jsonl",
                "agent_meta.json",
            )
        )
        try:
            from sase.agent.artifact_files_cache import get_global_cache

            selected = get_global_cache().select_prompt_file(
                artifacts_dir,
                is_workflow_child=agent.is_workflow_child,
                step_name=agent.step_name,
            )
        except (AttributeError, OSError, ValueError):
            selected = None
        if selected:
            paths.append(str(selected))
    if agent.response_path:
        paths.append(agent.response_path)
    return tuple(dict.fromkeys(paths))


def _path_token(path: str) -> tuple[str, int | None, int | None]:
    try:
        stat = Path(path).stat()
    except OSError:
        return (path, None, None)
    return (path, stat.st_mtime_ns, stat.st_size)


def _append_section_header(text: Text, label: str, accent: str) -> None:
    text.append(label, style=f"bold {accent}")
    text.append(" " + "─" * max(3, 34 - len(label)), style=f"dim {accent}")
    text.append("\n")


def _prompt_label(payload: NodeFinderPreviewPayload) -> str:
    return f"PROMPT · {payload.source_name}" if payload.source_name else "PROMPT"


__all__ = [
    "NodeFinderPreviewCache",
    "NodeFinderPreviewPayload",
    "PreviewToken",
    "load_node_finder_preview",
    "node_finder_preview_token",
    "render_tier1",
    "tier1_source",
]

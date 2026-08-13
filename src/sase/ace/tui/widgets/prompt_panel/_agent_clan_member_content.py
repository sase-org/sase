"""Disk-backed content loading and invalidation for clan members."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sase.agent.artifact_files_cache import get_global_cache
from sase.ace.tui.tools import SlowToolSource, build_slow_tool_sources
from sase.main.init_memory.config import project_memory_name
from sase.memory.read_log import memory_read_log_path
from sase.skills.use_log import skill_use_log_path

from ...models._agent_clan_sections import (
    ClanAgentIdentity,
    ClanDiskMemberSnapshot,
    ClanDiskSection,
    ClanTextEntry,
    first_meaningful_line,
)
from ...models.agent import Agent
from ._agent_display_content import get_prompt_content
from ._agent_display_header_summary import build_detail_header_summary
from ._agent_display_state import ALL_DETAIL_CONTEXT_LANES, DetailHeaderSummary
from ._helpers import format_output


def load_clan_disk_member_snapshot(
    member: Agent,
    member_label: str,
    sections: frozenset[ClanDiskSection],
) -> ClanDiskMemberSnapshot:
    """Load requested content for one real member outside the event loop."""
    replies = (
        _load_member_replies(member, member_label) if "replies" in sections else ()
    )
    prompts = (
        _load_member_prompts(member, member_label) if "prompts" in sections else ()
    )
    needs_context = "context" in sections
    needs_slow_tools = "slow-tool-calls" in sections
    context: DetailHeaderSummary | None = None
    slow_tool_sources: tuple[SlowToolSource, ...] | None = None
    if needs_context:
        lanes = ALL_DETAIL_CONTEXT_LANES - {"page-url"}
        if not needs_slow_tools:
            lanes = lanes - {"slow-tools"}
        context = build_detail_header_summary(member, lanes=lanes)
        slow_tool_sources = context.slow_tool_sources
    elif needs_slow_tools:
        slow_tool_sources = build_slow_tool_sources(member)
    return ClanDiskMemberSnapshot(
        member_identity=member.identity,
        member_label=member_label,
        loaded_sections=sections,
        replies=replies,
        prompts=prompts,
        context=context,
        slow_tool_sources=slow_tool_sources,
    )


def clan_member_source_token(member: Agent) -> tuple[object, ...]:
    """Return the member's in-memory inputs plus disk source mtimes.

    This function intentionally performs filesystem work and must only be
    called by the clan worker. Direct artifact-file signatures cover prompt,
    reply, context-marker, and tool-call sources without any render-time glob.
    """
    source_paths: list[Path] = []
    rows = (member, *member.runtime_children, *member.followup_agents)
    seen_rows: set[ClanAgentIdentity] = set()
    for row in rows:
        if row.identity in seen_rows:
            continue
        seen_rows.add(row.identity)
        artifacts_dir = row.get_artifacts_dir()
        if artifacts_dir:
            artifact_root = Path(artifacts_dir).expanduser()
            source_paths.extend(_direct_artifact_sources(artifact_root))
            source_paths.extend(_chat_source_paths(artifact_root))
        for path_value in (
            row.response_path,
            row.plan_path,
            row.archived_plan_path,
            row.sdd_plan_path,
            row.epic_plan_ref,
        ):
            if path_value:
                source_paths.append(Path(path_value).expanduser())
        source_paths.extend(_audit_log_paths(row))

    path_token = tuple(
        sorted(
            (_path_signature(path) for path in source_paths),
            key=lambda item: item[0],
        )
    )
    state_token = (
        member.status,
        member.stop_time.isoformat() if member.stop_time is not None else None,
        member.response_path,
        member.artifacts_dir,
        member.plan_path,
        member.archived_plan_path,
        member.sdd_plan_path,
        member.epic_plan_ref,
        member.epic_bead_id,
        member.phase_bead_id,
        member.workspace_dir,
        member.workspace_num,
        json.dumps(member.step_output, sort_keys=True, default=str)
        if member.step_output is not None
        else None,
    )
    return (member.identity, state_token, path_token)


def _load_member_replies(
    member: Agent,
    member_label: str,
) -> tuple[ClanTextEntry, ...]:
    if not member.is_agent_entry and member.step_output is not None:
        body = format_output(member.step_output).strip()
        if body:
            return (_text_entry(member, member_label, "STEP OUTPUT", body),)

    chunks = member.get_timestamped_reply_chunks()
    if chunks:
        body = "\n\n".join(chunk.strip() for _, chunk in chunks if chunk.strip())
        if body:
            return (_text_entry(member, member_label, "AGENT CHAT", body),)
    live_reply = member.get_live_reply_content()
    if live_reply:
        return (_text_entry(member, member_label, "AGENT CHAT", live_reply),)
    response = member.get_response_content()
    if response:
        return (_text_entry(member, member_label, "AGENT REPLY", response),)
    chat = member.get_chat_response_content()
    if chat:
        return (_text_entry(member, member_label, "AGENT CHAT", chat),)
    return ()


def _load_member_prompts(
    member: Agent,
    member_label: str,
) -> tuple[ClanTextEntry, ...]:
    entries: list[ClanTextEntry] = []
    raw_xprompt = member.get_raw_xprompt_content()
    if raw_xprompt:
        entries.append(_text_entry(member, member_label, "AGENT XPROMPT", raw_xprompt))
    prompt = get_prompt_content(member)
    if prompt:
        entries.append(_text_entry(member, member_label, "AGENT PROMPT", prompt))
    return tuple(entries)


def _text_entry(
    member: Agent,
    member_label: str,
    kind: str,
    body: str,
) -> ClanTextEntry:
    normalized = body.strip()
    return ClanTextEntry(
        member_identity=member.identity,
        member_label=member_label,
        kind=kind,
        preview=first_meaningful_line(normalized),
        body=normalized,
    )


def _direct_artifact_sources(artifact_root: Path) -> tuple[Path, ...]:
    paths = [artifact_root]
    try:
        paths.extend(
            entry
            for entry in artifact_root.iterdir()
            if entry.is_file() or entry.is_dir()
        )
    except OSError:
        pass
    return tuple(paths)


def _chat_source_paths(artifact_root: Path) -> tuple[Path, ...]:
    meta_path = artifact_root / "agent_meta.json"
    data = get_global_cache().read_json(str(meta_path))
    if not isinstance(data, dict):
        return ()
    chat_path = data.get("chat_path")
    if not isinstance(chat_path, str) or not chat_path:
        return ()
    return (Path(os.path.expanduser(chat_path)),)


def _audit_log_paths(member: Agent) -> tuple[Path, ...]:
    try:
        context_path = (
            Path(member.workspace_dir) if member.workspace_dir else Path.cwd()
        )
        project = project_memory_name(context_path)
    except Exception:
        return ()
    return (memory_read_log_path(project), skill_use_log_path(project))


def _path_signature(path: Path) -> tuple[str, int, int]:
    try:
        normalized = path.resolve(strict=False)
    except OSError:
        normalized = path.absolute()
    try:
        stat = normalized.stat()
    except OSError:
        return (str(normalized), 0, 0)
    return (str(normalized), stat.st_mtime_ns, stat.st_size)

"""Source-scoped tool-call helpers for slow-call display surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    agent_family_base,
    agent_family_role_for_suffix,
    plan_chain_feedback_round,
)

from ._entry import ToolCallEntry
from .cache import (
    cached_tool_calls_end_reference,
    fetch_tool_calls_cached,
    peek_tool_calls_cache_entry,
)
from .slow import agent_is_active_for_slow_tool_calls

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


@dataclass(frozen=True)
class SlowToolSource:
    """Tool calls attributed to one selected-row source."""

    label: str | None
    entries: tuple[ToolCallEntry, ...]
    agent_is_active: bool
    end_reference: datetime | None
    palette_index: int


def supports_slow_tool_sources(agent: Agent) -> bool:
    """Return whether ``agent`` can display source-scoped tool calls."""
    if agent.is_agent_entry:
        return True
    return any(child.is_agent_entry for child in getattr(agent, "runtime_children", ()))


def build_slow_tool_sources(agent: Agent) -> tuple[SlowToolSource, ...] | None:
    """Build source-scoped tool-call entries for ``agent``.

    This may stat/read artifact files through :func:`fetch_tool_calls_cached`;
    callers should run it off the Textual event loop.
    """
    children = _agent_entry_runtime_children(agent)
    if not children:
        return _build_leaf_source(agent)
    return _build_root_sources(agent, children)


def build_cached_slow_tool_sources(agent: Agent) -> tuple[SlowToolSource, ...] | None:
    """Build source-scoped entries from cache metadata only.

    This helper does no path resolution, stat calls, or artifact reads. It is
    intended for event-loop callers that want to render already-cached rows.
    """
    children = _agent_entry_runtime_children(agent)
    if not children:
        return _build_cached_leaf_source(agent)
    return _build_cached_root_sources(agent, children)


def _build_leaf_source(agent: Agent) -> tuple[SlowToolSource, ...] | None:
    artifacts_dir = _resolved_artifacts_dir(agent)
    if artifacts_dir is None:
        return None

    entries = fetch_tool_calls_cached(agent)
    if entries is None:
        return None

    return (
        SlowToolSource(
            label=None,
            entries=_entries_for_dir(entries, artifacts_dir),
            agent_is_active=agent_is_active_for_slow_tool_calls(agent),
            end_reference=_source_end_reference(agent),
            palette_index=0,
        ),
    )


def _build_cached_leaf_source(agent: Agent) -> tuple[SlowToolSource, ...] | None:
    cache_entry = peek_tool_calls_cache_entry(agent)
    if cache_entry is None or cache_entry.entries is None:
        return None

    artifacts_dir = _cached_source_dir(
        cache_entry.discovered_dirs,
        cache_entry.entries,
    )
    entries = (
        _entries_for_cached_dir(cache_entry.entries, artifacts_dir)
        if artifacts_dir is not None
        else tuple(cache_entry.entries)
    )
    return (
        SlowToolSource(
            label=None,
            entries=entries,
            agent_is_active=agent_is_active_for_slow_tool_calls(agent),
            end_reference=_source_end_reference(agent),
            palette_index=0,
        ),
    )


def _build_root_sources(
    root: Agent,
    children: tuple[Agent, ...],
) -> tuple[SlowToolSource, ...] | None:
    claimed: set[Path] = set()
    source_specs: list[tuple[Agent, Path, str | None]] = []

    for child in children:
        artifacts_dir = _resolved_artifacts_dir(child)
        if artifacts_dir is None or artifacts_dir in claimed:
            continue
        claimed.add(artifacts_dir)
        source_specs.append((child, artifacts_dir, _source_label(child, root=root)))

    root_dir = _resolved_artifacts_dir(root)
    if root_dir is not None and root_dir not in claimed:
        source_specs.append((root, root_dir, "root"))

    sources: list[SlowToolSource] = []
    for row, artifacts_dir, label in source_specs:
        entries = fetch_tool_calls_cached(row)
        if entries is None:
            continue
        sources.append(
            SlowToolSource(
                label=label,
                entries=_entries_for_dir(entries, artifacts_dir),
                agent_is_active=agent_is_active_for_slow_tool_calls(row),
                end_reference=_source_end_reference(row),
                palette_index=len(sources),
            )
        )

    return tuple(sources) if sources else None


def _build_cached_root_sources(
    root: Agent,
    children: tuple[Agent, ...],
) -> tuple[SlowToolSource, ...] | None:
    claimed: set[str] = set()
    source_specs: list[tuple[Agent, str, str | None]] = []

    for child in children:
        cache_entry = peek_tool_calls_cache_entry(child)
        if cache_entry is None or cache_entry.entries is None:
            continue
        artifacts_dir = _cached_source_dir(
            cache_entry.discovered_dirs,
            cache_entry.entries,
        )
        if artifacts_dir is None or artifacts_dir in claimed:
            continue
        claimed.add(artifacts_dir)
        source_specs.append((child, artifacts_dir, _source_label(child, root=root)))

    root_cache_entry = peek_tool_calls_cache_entry(root)
    if root_cache_entry is not None and root_cache_entry.entries is not None:
        root_dir = _cached_source_dir(
            root_cache_entry.discovered_dirs,
            root_cache_entry.entries,
        )
        if root_dir is not None and root_dir not in claimed:
            source_specs.append((root, root_dir, "root"))

    sources: list[SlowToolSource] = []
    for row, artifacts_dir, label in source_specs:
        cache_entry = peek_tool_calls_cache_entry(row)
        if cache_entry is None or cache_entry.entries is None:
            continue
        sources.append(
            SlowToolSource(
                label=label,
                entries=_entries_for_cached_dir(cache_entry.entries, artifacts_dir),
                agent_is_active=agent_is_active_for_slow_tool_calls(row),
                end_reference=_source_end_reference(row),
                palette_index=len(sources),
            )
        )

    return tuple(sources) if sources else None


def _agent_entry_runtime_children(agent: Agent) -> tuple[Agent, ...]:
    return tuple(
        child
        for child in getattr(agent, "runtime_children", ())
        if getattr(child, "is_agent_entry", False)
    )


def _resolved_artifacts_dir(agent: Agent) -> Path | None:
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None
    artifacts_dir = get_artifacts_dir()
    if not isinstance(artifacts_dir, (str, Path)) or not artifacts_dir:
        return None
    return _path_identity(Path(artifacts_dir).expanduser())


def _cached_source_dir(
    discovered_dirs: list[Path],
    entries: tuple[ToolCallEntry, ...],
) -> str | None:
    if discovered_dirs:
        return str(discovered_dirs[0])
    for entry in entries:
        if entry.artifact_dir:
            return entry.artifact_dir
    return None


def _entries_for_cached_dir(
    entries: tuple[ToolCallEntry, ...],
    artifacts_dir: str,
) -> tuple[ToolCallEntry, ...]:
    return tuple(entry for entry in entries if entry.artifact_dir == artifacts_dir)


def _entries_for_dir(
    entries: tuple[ToolCallEntry, ...],
    artifacts_dir: Path,
) -> tuple[ToolCallEntry, ...]:
    return tuple(
        entry
        for entry in entries
        if entry.artifact_dir is not None
        and _path_identity(Path(entry.artifact_dir).expanduser()) == artifacts_dir
    )


def _source_end_reference(agent: Agent) -> datetime | None:
    return getattr(agent, "stop_time", None) or cached_tool_calls_end_reference(agent)


def _source_label(agent: Agent, *, root: Agent) -> str:
    feedback_round = plan_chain_feedback_round(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )
    if feedback_round is not None:
        return f"fb{feedback_round}"

    role = agent_family_role_for_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )
    if role and role != "root":
        return role

    if agent.step_name:
        return agent.step_name

    if agent.agent_name:
        base = agent_family_base(root.agent_name)
        if base and agent.agent_name.startswith(f"{base}{AGENT_FAMILY_SEPARATOR}"):
            return agent.agent_name[len(base) + len(AGENT_FAMILY_SEPARATOR) :]
        if root.agent_name and agent.agent_name.startswith(
            f"{root.agent_name}{AGENT_FAMILY_SEPARATOR}"
        ):
            return agent.agent_name[
                len(root.agent_name) + len(AGENT_FAMILY_SEPARATOR) :
            ]
        return agent.presented_agent_name or agent.agent_name

    return agent.display_name


def _path_identity(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


__all__ = [
    "SlowToolSource",
    "build_cached_slow_tool_sources",
    "build_slow_tool_sources",
    "supports_slow_tool_sources",
]

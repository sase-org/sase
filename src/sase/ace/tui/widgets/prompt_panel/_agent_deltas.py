"""Agent-specific DELTAS helpers for the prompt panel header."""

from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Iterable
from typing import TYPE_CHECKING

from rich.text import Text

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.deltas.compute import semantic_line_stats

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ..deltas_builder import build_delta_entries_section
from ..file_panel._diff import diff_badge_uses_live_hint, get_agent_diff
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ..hint_tracker import HintTracker
from ._agent_commits import CommitDiffInfo, agent_commit_diffs
from ._helpers import mark_section_heading

if TYPE_CHECKING:
    from ._agent_display_state import HeaderHintState


@dataclass
class _DiffFile:
    old_path: str | None = None
    new_path: str | None = None
    rename_to: str | None = None
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    raw_added: int = 0
    raw_removed: int = 0


def _strip_diff_prefix(path: str) -> str:
    path = path.strip()
    if path == "/dev/null":
        return path
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _parse_header_path(line: str, prefix: str) -> str | None:
    if not line.startswith(prefix):
        return None
    # Git quotes paths containing special characters. Keep the parser small:
    # common unquoted paths are enough for display, and quoted paths degrade to
    # a harmless quoted string instead of failing the whole DELTAS section.
    value = line[len(prefix) :].split("\t", 1)[0].strip()
    if not value:
        return None
    return _strip_diff_prefix(value)


def _finalize_diff_file(current: _DiffFile | None) -> DeltaEntry | None:
    if current is None:
        return None

    if current.is_deleted or current.new_path == "/dev/null":
        path = current.old_path
    else:
        path = current.rename_to or current.new_path or current.old_path
    if not path or path == "/dev/null":
        return None

    if current.is_new or current.old_path == "/dev/null":
        change_type = "A"
    elif current.is_deleted or current.new_path == "/dev/null":
        change_type = "D"
    else:
        change_type = "M"

    stats: DeltaLineStats | None
    if current.is_binary:
        stats = DeltaLineStats(binary=True)
    else:
        stats = semantic_line_stats(str(current.raw_added), str(current.raw_removed))

    return DeltaEntry(path=path, change_type=change_type, line_stats=stats)


def parse_unified_diff_deltas(diff_text: str) -> list[DeltaEntry]:
    """Parse unified diff text into per-file DELTAS entries."""
    entries: list[DeltaEntry] = []
    current: _DiffFile | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            entry = _finalize_diff_file(current)
            if entry is not None:
                entries.append(entry)
            current = _DiffFile()
            parts = line.split()
            if len(parts) >= 4:
                current.old_path = _strip_diff_prefix(parts[2])
                current.new_path = _strip_diff_prefix(parts[3])
            continue

        if current is None:
            continue

        if line.startswith("new file mode"):
            current.is_new = True
            continue
        if line.startswith("deleted file mode"):
            current.is_deleted = True
            continue
        if line.startswith("rename to "):
            current.rename_to = line.removeprefix("rename to ").strip()
            continue
        if line.startswith("Binary files ") or line == "GIT binary patch":
            current.is_binary = True
            continue

        old_path = _parse_header_path(line, "--- ")
        if old_path is not None:
            current.old_path = old_path
            if old_path == "/dev/null":
                current.is_new = True
            continue

        new_path = _parse_header_path(line, "+++ ")
        if new_path is not None:
            current.new_path = new_path
            if new_path == "/dev/null":
                current.is_deleted = True
            continue

        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            current.raw_added += 1
        elif line.startswith("-"):
            current.raw_removed += 1

    entry = _finalize_diff_file(current)
    if entry is not None:
        entries.append(entry)

    return sorted(entries, key=lambda e: e.path)


_parse_unified_diff_deltas = parse_unified_diff_deltas


def _normalized_agent_delta_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_commit_message_bookkeeping_path(path: str) -> bool:
    return _normalized_agent_delta_path(path) == "commit_message.md"


def visible_agent_delta_entries(entries: Iterable[DeltaEntry]) -> list[DeltaEntry]:
    """Return agent-display delta entries excluding SASE commit bookkeeping."""
    return [
        entry
        for entry in entries
        if not _is_commit_message_bookkeeping_path(entry.path)
    ]


def visible_agent_linked_delta_groups(
    groups: Iterable[LinkedDeltaGroup],
) -> tuple[LinkedDeltaGroup, ...]:
    visible_groups: list[LinkedDeltaGroup] = []
    for group in groups:
        entries = tuple(visible_agent_delta_entries(group.entries))
        if not entries:
            continue
        visible_groups.append(
            LinkedDeltaGroup(
                repo_name=group.repo_name,
                workspace_dir=group.workspace_dir,
                entries=entries,
                diff_text=group.diff_text,
                fetched_at=group.fetched_at,
                kind=group.kind,
            )
        )
    return tuple(visible_groups)


def _merge_line_stats(
    left: DeltaLineStats | None,
    right: DeltaLineStats | None,
) -> DeltaLineStats | None:
    if left is None and right is None:
        return None
    return DeltaLineStats(
        added=(left.added if left else 0) + (right.added if right else 0),
        modified=(left.modified if left else 0) + (right.modified if right else 0),
        removed=(left.removed if left else 0) + (right.removed if right else 0),
        binary=(left.binary if left else False) or (right.binary if right else False),
    )


def _merge_delta_entries(entries: Iterable[DeltaEntry]) -> list[DeltaEntry]:
    """Union per-commit delta entries by path, summing line stats.

    This is an approximation of the net diff: when a file has multiple change
    types across commits, the merged entry is marked modified. The exact
    base-to-head delta is unavailable after a terminal agent workspace is
    released, so persisted per-commit diffs are the reliable source.
    """
    merged: dict[str, DeltaEntry] = {}
    change_types: dict[str, set[str]] = {}
    for entry in entries:
        existing = merged.get(entry.path)
        if existing is None:
            merged[entry.path] = DeltaEntry(
                path=entry.path,
                change_type=entry.change_type,
                line_stats=entry.line_stats,
            )
            change_types[entry.path] = {entry.change_type}
            continue

        change_types[entry.path].add(entry.change_type)
        existing.line_stats = _merge_line_stats(existing.line_stats, entry.line_stats)
        if len(change_types[entry.path]) > 1:
            existing.change_type = "M"

    return sorted(merged.values(), key=lambda e: e.path)


def _read_commit_diff_text(diff_path: str) -> str | None:
    try:
        with open(os.path.expanduser(diff_path), encoding="utf-8") as f:
            diff_text = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    return diff_text if diff_text.strip() else None


def _commit_diff_delta_entries(
    commit_diffs: Iterable[CommitDiffInfo],
) -> tuple[list[DeltaEntry], str]:
    entries: list[DeltaEntry] = []
    diff_texts: list[str] = []
    for commit_diff in commit_diffs:
        diff_text = _read_commit_diff_text(commit_diff.diff_path)
        if not diff_text:
            continue
        diff_texts.append(diff_text)
        entries.extend(
            visible_agent_delta_entries(parse_unified_diff_deltas(diff_text))
        )
    return _merge_delta_entries(entries), "\n".join(diff_texts)


def agent_delta_entries(agent: Agent) -> list[DeltaEntry]:
    """Return the selected agent's own DELTAS entries when available."""
    if diff_badge_uses_live_hint(agent):
        # Active primary workspaces are fresh: show a dirty live diff before
        # persisted per-commit metadata. ``get_agent_diff`` falls back to the
        # persisted primary diff when the workspace is clean or unresolvable.
        diff_text = get_agent_diff(agent)
        if diff_text:
            return visible_agent_delta_entries(parse_unified_diff_deltas(diff_text))

    commit_diffs = agent_commit_diffs(agent)
    if commit_diffs:
        entries, _diff_text = _commit_diff_delta_entries(
            commit_diff for commit_diff in commit_diffs if commit_diff.is_primary
        )
        return entries

    diff_text = get_agent_diff(agent)
    if not diff_text:
        return []

    return visible_agent_delta_entries(parse_unified_diff_deltas(diff_text))


def agent_commit_linked_delta_groups(agent: Agent) -> tuple[LinkedDeltaGroup, ...]:
    """Build non-primary DELTAS groups from persisted per-commit diff files."""
    grouped: dict[tuple[str, str], list[CommitDiffInfo]] = {}
    group_order: list[tuple[str, str]] = []
    for commit_diff in agent_commit_diffs(agent):
        if commit_diff.is_primary:
            continue
        key = (commit_diff.repo_name, commit_diff.repo_kind)
        if key not in grouped:
            grouped[key] = []
            group_order.append(key)
        grouped[key].append(commit_diff)

    groups: list[LinkedDeltaGroup] = []
    for repo_name, repo_kind in sorted(
        group_order,
        key=lambda key: key[1] == "external",
    ):
        commit_infos = grouped[(repo_name, repo_kind)]
        entries, diff_text = _commit_diff_delta_entries(commit_infos)
        if not entries:
            continue
        groups.append(
            LinkedDeltaGroup(
                repo_name=repo_name,
                workspace_dir=commit_infos[0].workspace_dir,
                entries=tuple(entries),
                diff_text=diff_text,
                kind="external" if repo_kind == "external" else "linked",
            )
        )
    return tuple(groups)


def append_agent_deltas_section(
    text: Text,
    *,
    delta_entries: list[DeltaEntry] | None = None,
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = (),
    hint_state: HeaderHintState | None = None,
    indent: str = "",
    header_style: str = "bold #87D7FF",
) -> None:
    """Append precomputed delta entries when available."""
    deltas = visible_agent_delta_entries(delta_entries or [])
    linked_groups = visible_agent_linked_delta_groups(linked_delta_groups)
    if not deltas and not linked_groups:
        return

    heading_start = len(text)
    if hint_state is None:
        build_delta_entries_section(
            text,
            deltas,
            FoldLevel.FULLY_EXPANDED,
            header_label="Deltas:",
            linked_delta_groups=linked_groups,
            indent=indent,
            header_style=header_style,
        )
        mark_section_heading(
            text,
            "deltas",
            start=heading_start,
            end=heading_start + len("Deltas:"),
        )
        return

    tracker = HintTracker(
        counter=hint_state.hint_counter,
        mappings=dict(hint_state.hint_mappings),
        hook_hint_to_idx={},
        hint_to_entry_id={},
        mentor_hint_to_info={},
    )
    tracker = build_delta_entries_section(
        text,
        deltas,
        FoldLevel.FULLY_EXPANDED,
        tracker,
        show_file_hints=True,
        workspace_dir=hint_state.workspace_dir,
        header_label="Deltas:",
        linked_delta_groups=linked_groups,
        indent=indent,
        header_style=header_style,
    )
    hint_state.hint_counter = tracker.counter
    hint_state.hint_mappings.clear()
    hint_state.hint_mappings.update(tracker.mappings)
    mark_section_heading(
        text,
        "deltas",
        start=heading_start,
        end=heading_start + len("Deltas:"),
    )

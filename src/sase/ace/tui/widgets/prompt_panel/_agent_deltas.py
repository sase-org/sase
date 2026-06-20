"""Agent-specific DELTAS helpers for the prompt panel header."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.deltas.compute import semantic_line_stats

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ..deltas_builder import build_delta_entries_section
from ..file_panel._diff import get_agent_diff
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ..hint_tracker import HintTracker

if TYPE_CHECKING:
    from ._agent_display_parts import HeaderHintState


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


def agent_delta_entries(agent: Agent) -> list[DeltaEntry]:
    """Return the selected agent's own DELTAS entries when available."""
    diff_text = get_agent_diff(agent)
    if not diff_text:
        return []

    deltas = parse_unified_diff_deltas(diff_text)
    return deltas


def append_agent_deltas_section(
    text: Text,
    *,
    delta_entries: list[DeltaEntry] | None = None,
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = (),
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append precomputed delta entries when available."""
    deltas = delta_entries or []
    linked_groups = tuple(group for group in linked_delta_groups if group.entries)
    if not deltas and not linked_groups:
        return

    if hint_state is None:
        build_delta_entries_section(
            text,
            deltas,
            FoldLevel.FULLY_EXPANDED,
            header_label="Deltas:",
            linked_delta_groups=linked_groups,
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
    )
    hint_state.hint_counter = tracker.counter
    hint_state.hint_mappings.clear()
    hint_state.hint_mappings.update(tracker.mappings)

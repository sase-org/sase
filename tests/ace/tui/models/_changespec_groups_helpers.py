"""Shared helpers for the ``test_changespec_groups_*`` test modules."""

from __future__ import annotations

from datetime import datetime

from sase.ace.changespec import ChangeSpec, TimestampEntry
from sase.ace.tui.models.changespec_groups import ChangeSpecTreeEntry

_NOW = datetime(2026, 4, 26, 12, 0, 0)


def _cs(
    name: str,
    *,
    project: str = "demo",
    status: str = "WIP",
    timestamps: list[TimestampEntry] | None = None,
) -> ChangeSpec:
    """Build a minimal ChangeSpec for grouping/tree tests.

    ``project`` controls both the ``file_path`` parent dir (used by the
    cached ``project_name`` property) and the file basename, mirroring
    on-disk shape ``~/.sase/projects/<project>/<project>.gp``.
    """
    return ChangeSpec(
        name=name,
        description="",
        parent=None,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=f"/sase/projects/{project}/{project}.gp",
        line_number=1,
        timestamps=timestamps,
    )


def _kinds(entries: list[ChangeSpecTreeEntry]) -> list[tuple[str, int | None]]:
    """Reduce entries to ``(kind, level/changespec_idx)`` tuples."""
    out: list[tuple[str, int | None]] = []
    for e in entries:
        if e.kind == "group":
            assert e.group is not None
            out.append(("group", e.group.level))
        else:
            out.append(("changespec", e.changespec_idx))
    return out


def _group_keys(
    entries: list[ChangeSpecTreeEntry], level: int
) -> list[tuple[str, ...]]:
    return [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == level
    ]

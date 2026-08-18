"""Read access to the committed ``sase/task_types.json`` catalog snapshot.

The snapshot is written by ``sase memory init`` (D6) so a type unknown to this
machine's live registry can still be named -- and, once a snapshot writer
lands, presented -- from committed bytes rather than failing the read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def task_type_snapshot_entry(slug: str) -> Mapping[str, Any] | None:
    """Return the committed snapshot entry for *slug*, or ``None``.

    Absent, unreadable, or malformed snapshots degrade to ``None`` rather than
    raising: a missing plugin or a project with no snapshot yet is never a
    read failure (D3).
    """

    from sase.content_layout import discover_project_root, resolve_project_layout

    root = discover_project_root()
    if root is None:
        return None
    path = resolve_project_layout(root).namespace_root.path / "task_types.json"
    if not path.is_file():
        return None
    try:
        snapshot = require_rust_binding("parse_task_type_snapshot")(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return None
    if not isinstance(snapshot, Mapping):
        return None
    types = snapshot.get("types")
    if not isinstance(types, list):
        return None
    for entry in types:
        if isinstance(entry, Mapping) and str(entry.get("task_type") or "") == slug:
            return entry
    return None


__all__ = ["task_type_snapshot_entry"]

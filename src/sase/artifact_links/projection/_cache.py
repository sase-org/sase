"""Best-effort per-rule cache for the projection layer.

Every rule is independently best-effort: a rule whose input raises returns
its last cached rows rather than an empty tuple, so a transient failure
degrades the projection to staleness, never to a silent mass deletion of a
whole relation class. Cache writes are best-effort and never fail a read.
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any

from sase.agents_sync.io import atomic_write_json
from sase.core.paths import sase_projects_dir
from sase.memory.locks import locked_file

_CACHE_FILENAME = "artifact-link-projection.json"
_CACHE_SCHEMA_VERSION = 1


def _projection_cache_path(project_key: str) -> Path:
    """Return ``~/.sase/projects/<key>/artifact-link-projection.json``."""

    return sase_projects_dir() / project_key / _CACHE_FILENAME


def read_rule_cache(project_key: str, rule_id: str) -> tuple[Any, list[dict[str, Any]]]:
    """Return the cached ``(signature, rows)`` for *rule_id*.

    Returns ``(None, [])`` when *rule_id* has no prior cache entry.
    """

    path = _projection_cache_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        document = _read_document(path)
    entry = document["rules"].get(rule_id)
    if not isinstance(entry, dict):
        return None, []
    rows = entry.get("rows")
    if not isinstance(rows, list):
        return entry.get("signature"), []
    return entry.get("signature"), [dict(row) for row in rows if isinstance(row, dict)]


def write_rule_cache(
    project_key: str,
    rule_id: str,
    *,
    signature: Any,
    rows: list[dict[str, Any]],
) -> None:
    """Best-effort write of one rule's cache entry. Never raises."""

    path = _projection_cache_path(project_key)
    try:
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            document = _read_document(path)
            document["rules"][rule_id] = {"signature": signature, "rows": rows}
            atomic_write_json(path, document)
    except OSError:
        pass


def _read_document(path: Path) -> dict[str, Any]:
    empty: dict[str, Any] = {"schema_version": _CACHE_SCHEMA_VERSION, "rules": {}}
    if not path.is_file():
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), dict):
        return empty
    return payload

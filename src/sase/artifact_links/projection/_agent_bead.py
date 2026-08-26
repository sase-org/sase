"""Project `implements` rows from published agent metadata's bead fields."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path

from sase.agents_sync.v2_run_io import run_metadata_from_json
from sase.artifact_links.projection._cache import read_rule_cache, write_rule_cache
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs

_RULE_ID = "agent-bead"
_BEAD_METADATA_FIELDS = ("bead_id", "epic_bead_id", "phase_bead_id")


def project_agent_bead_rows(inputs: ProjectionInputs) -> tuple[ProjectedEdge, ...]:
    """Emit one row per non-empty bead field in a published agent's meta.json."""

    if inputs.agents_sidecar_root is None:
        return ()
    agents_dir = inputs.agents_sidecar_root / "agents"
    if not agents_dir.is_dir():
        return ()

    cached_signature, cached_rows = read_rule_cache(inputs.project_key, _RULE_ID)
    cached_stats = cached_signature if isinstance(cached_signature, dict) else {}
    cached_rows_by_agent = _rows_by_source_ref(cached_rows)

    try:
        meta_paths = _meta_paths_by_agent(agents_dir)
    except OSError:
        return _edges_from_rows(cached_rows)

    signature: dict[str, list[int]] = {}
    rows: list[dict[str, str]] = []
    changed = set(meta_paths) != set(cached_stats)
    for name, meta_path in meta_paths.items():
        try:
            stat = meta_path.stat()
        except OSError:
            continue
        stat_key = [stat.st_mtime_ns, stat.st_size]
        signature[name] = stat_key
        if cached_stats.get(name) == stat_key:
            rows.extend(cached_rows_by_agent.get(f"agent:{name}", ()))
            continue
        changed = True
        rows.extend(_rows_for_agent(meta_path, stat.st_mtime))

    if changed:
        write_rule_cache(inputs.project_key, _RULE_ID, signature=signature, rows=rows)
    return _edges_from_rows(rows)


def _rows_by_source_ref(
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    by_source: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_source.setdefault(row.get("source_ref", ""), []).append(row)
    return by_source


def _meta_paths_by_agent(agents_dir: Path) -> dict[str, Path]:
    # `entry.is_dir()` reuses the `readdir` stat scandir already fetched, and
    # a missing `meta.json` surfaces as the caller's later `.stat()` raising
    # rather than a second existence check here.
    with os.scandir(agents_dir) as it:
        names = sorted(
            entry.name for entry in it if entry.is_dir(follow_symlinks=False)
        )
    return {name: agents_dir / name / "meta.json" for name in names}


def _rows_for_agent(meta_path: Path, mtime: float) -> list[dict[str, str]]:
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        metadata = run_metadata_from_json(raw)
    except Exception:  # noqa: BLE001 - an unparseable agent contributes no row.
        return []
    fields = dict(metadata.metadata)
    created_at = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict[str, str]] = []
    for field_name in _BEAD_METADATA_FIELDS:
        value = fields.get(field_name)
        if not isinstance(value, str) or not value.strip():
            continue
        bead_id = value.strip()
        rows.append(
            {
                "source_ref": f"agent:{metadata.global_name}",
                "relation": "implements",
                "target_ref": f"bead:{bead_id}",
                "description": (
                    f"published meta.json's `{field_name}` field names bead {bead_id}"
                ),
                "created_at": created_at,
            }
        )
    return rows


def _edges_from_rows(rows: list[dict[str, str]]) -> tuple[ProjectedEdge, ...]:
    return tuple(
        ProjectedEdge(
            source_ref=row["source_ref"],
            relation=row["relation"],
            target_ref=row["target_ref"],
            description=row["description"],
            rule_id=_RULE_ID,
            created_at=row["created_at"],
        )
        for row in rows
    )


__all__ = ["project_agent_bead_rows"]

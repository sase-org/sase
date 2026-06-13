"""CLI helpers for agent artifact physical layout migration."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.core.agent_artifact_paths import (
    DAY_SHARDED_LAYOUT_VERSION,
    canonical_agent_artifact_path,
    iter_agent_artifact_dirs,
    parse_agent_artifact_path,
)
from sase.core.agent_scan_facade import (
    agent_artifact_index_status,
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from sase.core.paths import sase_projects_dir

_MANIFEST_SCHEMA_VERSION = 1
_ACE_RUN = "ace-run"
_LAYOUT_ALIAS_DDL = """
CREATE TABLE IF NOT EXISTS agent_artifact_aliases (
    alias_path TEXT PRIMARY KEY,
    artifact_dir TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_artifact_aliases_artifact_dir
    ON agent_artifact_aliases(artifact_dir);
"""


def handle_agents_artifacts_layout(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents artifacts layout`` subcommands."""
    sub = getattr(args, "layout_subcommand", None)
    if sub == "migrate":
        _handle_migrate(args)
        return
    if sub == "rollback":
        _handle_rollback(args)
        return
    if sub == "status":
        _handle_status(args)
        return
    if sub == "verify":
        _handle_verify(args)
        return
    Console().print(
        "Usage: sase agents artifacts layout {migrate,rollback,status,verify}"
    )
    raise SystemExit(1)


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    projects_root = Path(
        getattr(args, "projects_root", None) or sase_projects_dir()
    ).expanduser()
    index_path = Path(
        getattr(args, "index_path", None) or default_agent_artifact_index_path()
    ).expanduser()
    return projects_root, index_path


def _project_names(projects_root: Path, project: str | None) -> list[str]:
    if project:
        return [project]
    if not projects_root.is_dir():
        return []
    return sorted(path.name for path in projects_root.iterdir() if path.is_dir())


def _is_timestamp(value: str) -> bool:
    return len(value) == 14 and value.isdigit()


def _flat_ace_run_dirs(projects_root: Path, project_name: str) -> list[Path]:
    workflow_dir = projects_root / project_name / "artifacts" / _ACE_RUN
    if not workflow_dir.is_dir():
        return []
    try:
        children = sorted(workflow_dir.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    return [child for child in children if child.is_dir() and _is_timestamp(child.name)]


def _manifest_entry(
    projects_root: Path, project_name: str, old_path: Path
) -> dict[str, Any]:
    timestamp = old_path.name
    new_path = canonical_agent_artifact_path(
        project_name,
        _ACE_RUN,
        timestamp,
        projects_root=projects_root,
    )
    skip_reason = _skip_reason(old_path, new_path)
    return {
        "project_name": project_name,
        "timestamp": timestamp,
        "old_path": str(old_path),
        "new_path": str(new_path),
        "marker_files": [
            str(path)
            for path in _owned_marker_paths(old_path)
            if _marker_needs_rewrite(path, old_path)
        ],
        "status": "skipped" if skip_reason else "planned",
        "skip_reason": skip_reason,
    }


def _build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    projects_root, index_path = _paths(args)
    project = getattr(args, "project", None)
    limit = getattr(args, "limit", None)
    entries: list[dict[str, Any]] = []
    for project_name in _project_names(projects_root, project):
        for old_path in _flat_ace_run_dirs(projects_root, project_name):
            if limit is not None and len(entries) >= int(limit):
                break
            entries.append(_manifest_entry(projects_root, project_name, old_path))
        if limit is not None and len(entries) >= int(limit):
            break
    return {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "projects_root": str(projects_root),
        "index_path": str(index_path),
        "entries": entries,
    }


def _skip_reason(old_path: Path, new_path: Path) -> str | None:
    if (old_path / "running.json").exists():
        return "running_marker_present"
    live_env = os.environ.get("SASE_ARTIFACTS_DIR")
    if live_env and Path(live_env).expanduser().resolve(
        strict=False
    ) == old_path.resolve(strict=False):
        return "current_sase_artifacts_dir"
    if new_path.exists() and new_path.resolve(strict=False) != old_path.resolve(
        strict=False
    ):
        return "target_exists"
    return None


def _owned_marker_paths(artifact_dir: Path) -> Iterable[Path]:
    yield artifact_dir / "workflow_state.json"
    try:
        yield from sorted(artifact_dir.glob("prompt_step_*.json"))
    except OSError:
        return


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _marker_needs_rewrite(path: Path, old_path: Path) -> bool:
    data = _read_json_dict(path)
    return data is not None and data.get("artifacts_dir") == str(old_path)


def _rewrite_marker_paths(artifact_dir: Path, old_value: str, new_value: str) -> int:
    rewritten = 0
    for path in _owned_marker_paths(artifact_dir):
        data = _read_json_dict(path)
        if data is None or data.get("artifacts_dir") != old_value:
            continue
        data["artifacts_dir"] = new_value
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        rewritten += 1
    return rewritten


def _write_alias(index_path: Path, old_path: str, new_path: str) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(index_path)) as conn:
        with conn:
            conn.executescript(_LAYOUT_ALIAS_DDL)
            conn.execute(
                "INSERT OR REPLACE INTO agent_artifact_aliases(alias_path, artifact_dir) VALUES (?, ?)",
                (old_path, new_path),
            )


def _delete_alias(index_path: Path, old_path: str, new_path: str) -> None:
    if not index_path.exists():
        return
    with closing(sqlite3.connect(index_path)) as conn:
        with conn:
            conn.executescript(_LAYOUT_ALIAS_DDL)
            conn.execute(
                "DELETE FROM agent_artifact_aliases WHERE alias_path = ? OR artifact_dir = ?",
                (old_path, new_path),
            )


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError(f"unsupported artifact layout manifest: {path}")
    return payload


def _store_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _manifest_path(args: argparse.Namespace) -> Path | None:
    manifest_path = getattr(args, "manifest", None)
    return Path(manifest_path).expanduser() if manifest_path else None


def _persist_manifest_if_requested(
    args: argparse.Namespace, payload: dict[str, Any]
) -> None:
    path = _manifest_path(args)
    if path is not None and "entries" in payload:
        _store_manifest(path, payload)


def _handle_migrate(args: argparse.Namespace) -> None:
    projects_root, index_path = _paths(args)
    manifest = _build_manifest(args)
    dry_run = bool(getattr(args, "dry_run", False))
    if dry_run:
        _finish_payload(args, manifest)
        return

    _persist_manifest_if_requested(args, manifest)

    moved = 0
    rewritten = 0
    for entry in manifest["entries"]:
        if entry["status"] == "skipped":
            continue
        old_path = Path(entry["old_path"])
        new_path = Path(entry["new_path"])
        reason = _skip_reason(old_path, new_path)
        if reason:
            entry["status"] = "skipped"
            entry["skip_reason"] = reason
            continue
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            os.rename(old_path, new_path)
            moved += 1
            rewritten += _rewrite_marker_paths(new_path, str(old_path), str(new_path))
            _write_alias(index_path, str(old_path), str(new_path))
        except Exception as exc:
            entry["status"] = "failed"
            entry["failure_reason"] = str(exc)
            continue
        entry["status"] = "migrated"

    manifest["moved"] = moved
    manifest["marker_files_rewritten"] = rewritten
    _persist_manifest_if_requested(args, manifest)
    if moved:
        try:
            rebuild_agent_artifact_index(index_path, projects_root)
        except Exception as exc:
            manifest["index_rebuild_error"] = str(exc)
            _finish_payload(args, manifest)
            raise SystemExit(1) from exc
    _finish_payload(args, manifest)


def _handle_rollback(args: argparse.Namespace) -> None:
    projects_root, index_path = _paths(args)
    manifest_path = Path(getattr(args, "manifest", "") or "")
    if not manifest_path:
        raise SystemExit("rollback requires -m|--manifest")
    manifest = _load_manifest(manifest_path.expanduser())
    moved = 0
    rewritten = 0
    for entry in manifest.get("entries", []):
        if entry.get("status") not in {"migrated", "planned", "failed"}:
            continue
        old_path = Path(entry["old_path"])
        new_path = Path(entry["new_path"])
        if not new_path.exists() or old_path.exists():
            continue
        old_path.parent.mkdir(parents=True, exist_ok=True)
        os.rename(new_path, old_path)
        moved += 1
        rewritten += _rewrite_marker_paths(old_path, str(new_path), str(old_path))
        _delete_alias(index_path, str(old_path), str(new_path))
        entry["status"] = "rolled_back"

    if moved:
        rebuild_agent_artifact_index(index_path, projects_root)
    payload = {"rolled_back": moved, "marker_files_rewritten": rewritten, **manifest}
    _finish_payload(args, payload)


def _handle_status(args: argparse.Namespace) -> None:
    projects_root, index_path = _paths(args)
    project = getattr(args, "project", None)
    flat_dirs = 0
    sharded_dirs = 0
    active_dirs = 0
    for project_name in _project_names(projects_root, project):
        flat_dirs += len(_flat_ace_run_dirs(projects_root, project_name))
        for artifact_dir in iter_agent_artifact_dirs(
            project_name,
            _ACE_RUN,
            projects_root=projects_root,
        ):
            info = parse_agent_artifact_path(artifact_dir, projects_root=projects_root)
            if info is not None and info.layout_version == DAY_SHARDED_LAYOUT_VERSION:
                sharded_dirs += 1
            if (artifact_dir / "running.json").exists():
                active_dirs += 1

    index_error: str | None
    try:
        status = agent_artifact_index_status(index_path)
        indexed_rows = status.agent_artifacts_rows
        alias_rows = status.agent_artifact_aliases_rows
        dismissed_rows = status.dismissed_agents_rows
        schema_version = status.schema_version
    except Exception as exc:
        indexed_rows = alias_rows = dismissed_rows = schema_version = 0
        index_error = str(exc)
    else:
        index_error = None

    payload = {
        "active_dirs": active_dirs,
        "alias_rows": alias_rows,
        "dismissed_rows": dismissed_rows,
        "flat_dirs": flat_dirs,
        "index_error": index_error,
        "index_path": str(index_path),
        "indexed_rows": indexed_rows,
        "migration_recommended": flat_dirs > 0,
        "projects_root": str(projects_root),
        "schema_version": schema_version,
        "sharded_dirs": sharded_dirs,
    }
    _finish_payload(args, payload)


def _handle_verify(args: argparse.Namespace) -> None:
    manifest_path = Path(getattr(args, "manifest", "") or "")
    if not manifest_path:
        payload = _build_manifest(args)
        payload["ok"] = not any(
            entry["status"] != "skipped" for entry in payload["entries"]
        )
        _finish_payload(args, payload)
        return

    projects_root, index_path = _paths(args)
    manifest = _load_manifest(manifest_path.expanduser())
    checked = 0
    failures: list[dict[str, str]] = []
    aliases = _read_aliases(index_path)
    for entry in manifest.get("entries", []):
        if entry.get("status") == "skipped":
            continue
        checked += 1
        old_path = Path(entry["old_path"])
        new_path = Path(entry["new_path"])
        if not new_path.is_dir():
            failures.append({"path": str(new_path), "reason": "missing_new_path"})
        if old_path.exists():
            failures.append({"path": str(old_path), "reason": "old_path_still_exists"})
        if aliases.get(str(old_path)) != str(new_path):
            failures.append({"path": str(old_path), "reason": "missing_alias"})
    payload = {
        "checked": checked,
        "failures": failures,
        "ok": not failures,
        "projects_root": str(projects_root),
    }
    _finish_payload(args, payload)
    if failures:
        raise SystemExit(1)


def _read_aliases(index_path: Path) -> dict[str, str]:
    if not index_path.exists():
        return {}
    with closing(sqlite3.connect(index_path)) as conn:
        conn.executescript(_LAYOUT_ALIAS_DDL)
        return dict(
            conn.execute("SELECT alias_path, artifact_dir FROM agent_artifact_aliases")
        )


def _finish_payload(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    _persist_manifest_if_requested(args, payload)
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
        return
    Console().print(json.dumps(payload, indent=2, sort_keys=True))


__all__ = ["handle_agents_artifacts_layout"]

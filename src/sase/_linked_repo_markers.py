"""Opened-workspace marker persistence for linked repositories."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Literal

from sase._linked_repo_config import normalize_path

OPENED_LINKED_FILENAME = "opened_linked_workspaces.json"
OPENED_SIBLINGS_FILENAME = "opened_siblings.json"

_OPENED_SCHEMA_VERSION = 3

OpenedRepoKind = Literal["linked", "external"]


def record_opened_linked_repo(
    name: str,
    workspace_dir: str,
    *,
    reason: str = "",
    opened_at: str | None = None,
) -> None:
    """Record that the current agent run opened a configured linked repo.

    During the migration both the canonical ``opened_linked_workspaces.json``
    and the legacy ``opened_siblings.json`` markers are written.
    """

    record_opened_repo(
        name,
        workspace_dir,
        kind="linked",
        reason=reason,
        opened_at=opened_at,
    )


def record_opened_external_repo(
    canonical_ref: str,
    workspace_dir: str,
    *,
    reason: str = "",
    opened_at: str | None = None,
) -> None:
    """Record an external repo under its canonical provider or project ref."""

    record_opened_repo(
        canonical_ref,
        workspace_dir,
        kind="external",
        ref=canonical_ref,
        reason=reason,
        opened_at=opened_at,
    )


def record_opened_repo(
    name: str,
    workspace_dir: str,
    *,
    kind: OpenedRepoKind,
    ref: str | None = None,
    reason: str = "",
    opened_at: str | None = None,
) -> None:
    """Record a linked or external repo opened by the current agent run."""

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    normalized_name = name.strip()
    if not normalized_name:
        return
    normalized_reason = reason.strip()
    normalized_opened_at = (opened_at or "").strip()
    if kind not in {"linked", "external"}:
        return
    normalized_ref = (ref or normalized_name).strip()
    if kind == "external" and not normalized_ref:
        return

    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    marker_targets = [(OPENED_LINKED_FILENAME, "linked_repos")]
    if kind == "linked":
        marker_targets.append((OPENED_SIBLINGS_FILENAME, "siblings"))

    for filename, records_key in marker_targets:
        marker = root / filename
        records = _opened_records(marker)
        baseline_error = _capture_opened_repo_baseline(
            repo_id=f"{kind}:{normalized_name}",
            workspace_dir=workspace_dir,
            kind=kind,
            name=normalized_name,
            artifacts_dir=str(root),
        )
        record = {
            "name": normalized_name,
            "workspace_dir": normalize_path(workspace_dir),
            "reason": normalized_reason,
            "opened_at": normalized_opened_at,
            "kind": kind,
        }
        if kind == "external":
            record["ref"] = normalized_ref
        if baseline_error:
            record["baseline_error"] = baseline_error
        records[normalized_name] = record
        _write_opened_marker(marker, records, records_key)


def opened_linked_repo_names(artifact_root: Path | None) -> set[str]:
    """Return linked repo names opened during the agent run."""

    return set(opened_linked_repo_records(artifact_root))


def opened_linked_repo_workspace_dirs(artifact_root: Path | None) -> dict[str, str]:
    """Return opened linked repo names mapped to their recorded workspace dirs."""

    return {
        name: record.get("workspace_dir", "")
        for name, record in opened_linked_repo_records(artifact_root).items()
    }


def opened_linked_repo_records(artifact_root: Path | None) -> dict[str, dict[str, str]]:
    """Return full opened linked-repo records keyed by linked repo name."""

    return {
        name: record
        for name, record in opened_repo_records(artifact_root).items()
        if record["kind"] == "linked"
    }


def opened_external_repo_records(
    artifact_root: Path | None,
) -> dict[str, dict[str, str]]:
    """Return full opened external-repo records keyed by canonical name."""

    return {
        name: record
        for name, record in opened_repo_records(artifact_root).items()
        if record["kind"] == "external"
    }


def opened_repo_records(artifact_root: Path | None) -> dict[str, dict[str, str]]:
    """Return all opened repo records, with legacy entries typed as linked."""

    if artifact_root is None:
        return {}
    records: dict[str, dict[str, str]] = {}
    for filename in (OPENED_LINKED_FILENAME, OPENED_SIBLINGS_FILENAME):
        for name, record in _opened_records(artifact_root / filename).items():
            records.setdefault(name, record)
    return records


def _write_opened_marker(
    marker: Path, records: dict[str, dict[str, str]], records_key: str
) -> None:
    payload = {
        "schema_version": _OPENED_SCHEMA_VERSION,
        records_key: [records[key] for key in sorted(records)],
    }
    try:
        tmp = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, marker)
    except OSError:
        pass


def _opened_records(marker: Path) -> dict[str, dict[str, str]]:
    try:
        loaded = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, Mapping):
        return {}
    entries = loaded.get("linked_repos")
    if not isinstance(entries, list):
        entries = loaded.get("siblings")
    if not isinstance(entries, list):
        return {}

    records: dict[str, dict[str, str]] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        workspace_dir = item.get("workspace_dir")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(workspace_dir, str):
            workspace_dir = ""
        reason = item.get("reason")
        if not isinstance(reason, str):
            reason = ""
        opened_at = item.get("opened_at")
        if not isinstance(opened_at, str):
            opened_at = ""
        kind = item.get("kind", "linked")
        if kind not in {"linked", "external"}:
            continue
        normalized_name = name.strip()
        record = {
            "name": normalized_name,
            "workspace_dir": workspace_dir,
            "reason": reason.strip(),
            "opened_at": opened_at.strip(),
            "kind": kind,
        }
        if kind == "external":
            ref = item.get("ref")
            record["ref"] = ref.strip() if isinstance(ref, str) else normalized_name
        baseline_error = item.get("baseline_error")
        if isinstance(baseline_error, str) and baseline_error.strip():
            record["baseline_error"] = baseline_error.strip()
        records[normalized_name] = record
    return records


def _capture_opened_repo_baseline(
    *,
    repo_id: str,
    workspace_dir: str,
    kind: OpenedRepoKind,
    name: str,
    artifacts_dir: str,
) -> str | None:
    try:
        from sase.llm_provider.commit_finalizer_baseline import (
            capture_opened_repo_dirty_baseline,
        )

        return capture_opened_repo_dirty_baseline(
            repo_id,
            workspace_dir,
            kind=kind,
            name=name,
            artifacts_dir=artifacts_dir,
        )
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"

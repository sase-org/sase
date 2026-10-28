"""Transfer commit-finalizer responsibility to a continuation run."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Literal

from sase._linked_repo_config import normalize_path
from sase._linked_repo_markers import (
    merge_opened_repo_records,
    opened_repo_records,
)
from sase.agent.identity import AgentIdentity
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
    FinalizerBaselineRecord,
    load_finalizer_baseline_records,
)
from sase.repo_open_log import append_repo_open_event_once, build_repo_open_event

_logger = logging.getLogger(__name__)

INHERITANCE_DIAGNOSTICS_FILENAME = "opened_repo_inheritance_diagnostics.json"


def inherit_commit_finalizer_responsibility(
    *,
    parent_artifacts_dir: str | None,
    child_artifacts_dir: str,
    predecessor_name: str | None,
    successor_name: str | None,
    project_name: str | None,
    parent_workspace_dir: str | None,
    child_workspace_dir: str | None,
    workspace_num: int | None,
) -> bool:
    """Inherit a baseline and opened-repository discovery into a continuation.

    Returns whether a baseline is already present in the destination or was
    inherited. Known workspace changes deliberately start with a fresh
    baseline in the caller's resolved checkout; predecessor repository paths
    are never adopted in that case.
    """
    child_root = Path(child_artifacts_dir).expanduser().resolve(strict=False)
    child_root.mkdir(parents=True, exist_ok=True)
    diagnostics: list[str] = []

    parent_root = (
        Path(parent_artifacts_dir).expanduser().resolve(strict=False)
        if parent_artifacts_dir
        else None
    )
    parent_records = opened_repo_records(parent_root)
    source_baseline = _baseline_path(parent_root)
    child_has_baseline = _has_baseline(child_root)
    parent_workspace = _normalized_optional_path(parent_workspace_dir)
    child_workspace = _normalized_optional_path(child_workspace_dir)
    workspace_mismatch = bool(
        parent_workspace and child_workspace and parent_workspace != child_workspace
    )

    baseline_records = _read_canonical_records(parent_root, diagnostics)
    if workspace_mismatch:
        diagnostics.append(
            "The continuation is bound to a different workspace; predecessor "
            "baseline and opened-repository paths were not transferred. Capture "
            "a fresh baseline from the continuation's resolved workspace."
        )
        baseline_records = None
    elif not child_has_baseline and source_baseline is not None:
        try:
            shutil.copyfile(source_baseline, child_root / source_baseline.name)
            child_has_baseline = True
        except OSError as exc:
            diagnostics.append(
                f"Could not inherit {source_baseline.name}: {type(exc).__name__}: {exc}"
            )
            _logger.warning(
                "Could not inherit commit-finalizer baseline", exc_info=True
            )

    # A canonical opened_repo record is sufficient to reconstruct a missing
    # marker. Other baseline scopes and legacy fingerprint maps are not opened
    # repository inventories and must not create discovery records.
    inherited_records = dict(parent_records)
    if baseline_records is not None:
        for baseline_record in baseline_records:
            recovered = _marker_from_baseline(baseline_record)
            if recovered is not None:
                inherited_records.setdefault(recovered[0], recovered[1])

    transferable: dict[str, dict[str, str]] = {}
    for name, repo_record in inherited_records.items():
        path = normalize_path(repo_record.get("workspace_dir", ""))
        if not path:
            diagnostics.append(f"Opened repository {name!r} has no checkout path.")
            continue
        if workspace_mismatch or not _belongs_to_continuation_workspace(
            path,
            parent_workspace=parent_workspace,
            child_workspace=child_workspace,
        ):
            diagnostics.append(
                f"Opened repository {name!r} at {path} could not be transferred "
                "because its workspace ownership could not be verified."
            )
            continue
        if not _is_git_checkout(path):
            diagnostics.append(
                f"Opened repository {name!r} at {path} is unavailable in the "
                "continuation workspace."
            )
            continue
        transferable[name] = {**repo_record, "workspace_dir": path}

    # Child records win, including records opened during successor setup.
    before_merge = opened_repo_records(child_root)
    merged = merge_opened_repo_records(child_root, transferable)

    predecessor = _clean(predecessor_name) or "unknown predecessor"
    successor = _clean(successor_name)
    if successor is None:
        successor = _agent_name_from_meta(child_root) or "unknown continuation"
    project = _clean(project_name)
    workspace_number = _valid_workspace_num(workspace_num)
    for name, repo_record in transferable.items():
        destination_record = merged.get(name)
        if destination_record is None:
            continue
        repo_kind = _inherited_repo_kind(repo_record.get("kind", ""))
        if repo_kind is None:
            diagnostics.append(
                f"Opened repository {name!r} has an unsupported kind and was not audited."
            )
            continue
        if normalize_path(
            destination_record.get("workspace_dir", "")
        ) != normalize_path(repo_record["workspace_dir"]):
            diagnostics.append(
                f"The continuation already records {name!r} at a different checkout; "
                "the existing destination marker was preserved."
            )
            continue
        if name in before_merge and _record_is_successor_open(before_merge[name]):
            # Existing child metadata is authoritative. Its normal open event
            # already describes the child's interaction with this checkout.
            continue
        if project is None or workspace_number is None or child_workspace is None:
            diagnostics.append(
                f"Inherited repository {name!r} has no complete continuation audit "
                "identity/workspace binding."
            )
            continue
        reason = f"Inherited opened-repository responsibility from {predecessor}"
        event_id = _inherited_event_id(
            project=project,
            predecessor=predecessor,
            successor=successor,
            artifacts_dir=str(child_root),
            repo=name,
            path=repo_record["workspace_dir"],
        )
        try:
            event = build_repo_open_event(
                project=project,
                repo=name,
                repo_kind=repo_kind,
                workspace_num=workspace_number,
                path=repo_record["workspace_dir"],
                reason=reason,
                cwd=Path(child_workspace),
                open_id=event_id,
                agent=AgentIdentity(
                    name=successor,
                    source="agent_meta",
                    artifacts_dir=str(child_root),
                ),
            )
            append_repo_open_event_once(event)
        except Exception as exc:
            diagnostics.append(
                f"Could not audit inherited repository {name!r}: "
                f"{type(exc).__name__}: {exc}"
            )
            _logger.warning("Could not audit inherited repository open", exc_info=True)

    _write_diagnostics(child_root, predecessor, diagnostics)
    return child_has_baseline


def _baseline_path(root: Path | None) -> Path | None:
    if root is None:
        return None
    generic = root / FINALIZER_BASELINE_FILENAME
    if generic.is_file():
        return generic
    legacy = root / BASELINE_FILENAME
    return legacy if legacy.is_file() else None


def _has_baseline(root: Path) -> bool:
    return (root / FINALIZER_BASELINE_FILENAME).is_file() or (
        root / BASELINE_FILENAME
    ).is_file()


def _read_canonical_records(
    root: Path | None,
    diagnostics: list[str],
) -> tuple[FinalizerBaselineRecord, ...] | None:
    if root is None or not (root / FINALIZER_BASELINE_FILENAME).exists():
        return None
    records = load_finalizer_baseline_records(root)
    if records is None:
        diagnostics.append(
            f"The canonical baseline in {root} is missing or malformed; only marker "
            "metadata can be inherited."
        )
    return records


def _marker_from_baseline(
    record: FinalizerBaselineRecord,
) -> tuple[str, dict[str, str]] | None:
    if (
        record.scope != "opened_repo"
        or record.kind not in {"linked", "external"}
        or not record.name.strip()
        or record.repo_id != f"{record.kind}:{record.name}"
    ):
        return None
    name = record.name.strip()
    marker = {
        "name": name,
        "workspace_dir": record.path,
        "reason": "Recovered from an inherited opened_repo baseline",
        "opened_at": record.captured_at or "",
        "kind": record.kind,
    }
    if record.kind == "external":
        marker["ref"] = name
    return name, marker


def _belongs_to_continuation_workspace(
    repository_path: str,
    *,
    parent_workspace: str | None,
    child_workspace: str | None,
) -> bool:
    if parent_workspace and child_workspace:
        return parent_workspace == child_workspace
    if child_workspace is None:
        return False
    try:
        Path(repository_path).relative_to(Path(child_workspace))
    except ValueError:
        return False
    return True


def _is_git_checkout(path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and normalize_path(
        result.stdout.strip()
    ) == normalize_path(path)


def _record_is_successor_open(record: dict[str, str]) -> bool:
    reason = record.get("reason", "").lower()
    return not reason.startswith("inherited opened-repository responsibility")


def _inherited_event_id(
    *,
    project: str,
    predecessor: str,
    successor: str,
    artifacts_dir: str,
    repo: str,
    path: str,
) -> str:
    material = "\0".join((project, predecessor, successor, artifacts_dir, repo, path))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _write_diagnostics(
    root: Path,
    predecessor: str,
    diagnostics: list[str],
) -> None:
    path = root / INHERITANCE_DIAGNOSTICS_FILENAME
    if not diagnostics:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            _logger.debug(
                "Could not remove resolved inheritance diagnostics", exc_info=True
            )
        return
    payload: dict[str, Any] = {
        "schema_version": 1,
        "predecessor": predecessor,
        "diagnostics": diagnostics,
    }
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(tmp, path)
    except OSError:
        _logger.warning(
            "Could not persist opened-repository inheritance diagnostics",
            exc_info=True,
        )
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    for diagnostic in diagnostics:
        _logger.warning("Opened-repository inheritance: %s", diagnostic)


def _agent_name_from_meta(root: Path) -> str | None:
    try:
        payload = json.loads((root / "agent_meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = payload.get("name") if isinstance(payload, dict) else None
    return _clean(name)


def _normalized_optional_path(value: str | None) -> str | None:
    cleaned = _clean(value)
    return normalize_path(cleaned) if cleaned is not None else None


def _valid_workspace_num(value: int | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _inherited_repo_kind(value: str) -> Literal["linked", "external"] | None:
    if value == "linked":
        return "linked"
    if value == "external":
        return "external"
    return None


def _clean(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "INHERITANCE_DIAGNOSTICS_FILENAME",
    "inherit_commit_finalizer_responsibility",
]

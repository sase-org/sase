"""Storage, retention, and notification helpers for workspace rescue."""

from __future__ import annotations


import hashlib
import json

import logging

import os
import re

import shutil

import sys

import time

from dataclasses import dataclass

from datetime import UTC, datetime

from pathlib import Path


logger = logging.getLogger(__name__)


RESCUE_SCHEMA_VERSION = 1

RESCUE_MANIFEST_NAME = "manifest.json"

RESCUE_QUARANTINE_DIRNAME = "quarantined-clone"

RESCUE_ENTRY_RETENTION_DAYS = 30

RESCUE_QUARANTINE_RETENTION_DAYS = 7


_LABEL_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class RescueRecord:
    """What one rescue entry preserved, and where it lives."""

    rescue_dir: Path
    manifest_path: Path
    bundle_path: Path | None = None
    patch_path: Path | None = None
    quarantined_path: Path | None = None
    note: str | None = None


def quarantine_directory(
    path: str | Path,
    *,
    workspace_dir: str | Path,
    workspace_num: int,
    label: str,
    reason: str,
) -> RescueRecord | None:
    """Move a whole directory into a rescue entry outside the workspace.

    Falls back to ``None`` on ``EXDEV`` or any other ``OSError``. Never raises.
    """
    try:
        return _quarantine_directory(
            Path(path),
            workspace_dir=Path(workspace_dir),
            workspace_num=workspace_num,
            label=label,
            reason=reason,
        )
    except Exception:  # noqa: BLE001 - rescue must never break a launch.
        logger.warning("Workspace quarantine failed for %s", path, exc_info=True)
        return None


def reap_rescue_store(
    *,
    rescue_roots: list[Path] | None = None,
    now: float | None = None,
) -> None:
    """Delete aged rescue entries. Best-effort; never raises."""
    try:
        _reap_rescue_roots(rescue_roots=rescue_roots, now=now)
    except Exception:  # noqa: BLE001 - reaping must never break a launch.
        logger.debug("Rescue store reaping failed", exc_info=True)


def _quarantine_directory(
    path: Path,
    *,
    workspace_dir: Path,
    workspace_num: int,
    label: str,
    reason: str,
) -> RescueRecord | None:
    if not path.exists() and not os.path.lexists(path):
        return None
    safe_label = sanitize_label(label or path.name)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(f"{path}|{stamp}".encode()).hexdigest()[:8]
    rescue_dir = new_rescue_dir(
        workspace_dir,
        f"{stamp}-ws{workspace_num}-{safe_label}-{digest}",
    )
    rescue_dir.mkdir(parents=True, exist_ok=True)
    destination = rescue_dir / RESCUE_QUARANTINE_DIRNAME
    try:
        os.rename(path, destination)
    except OSError:
        shutil.rmtree(rescue_dir, ignore_errors=True)
        return None
    manifest = {
        "schema_version": RESCUE_SCHEMA_VERSION,
        "timestamp": stamp,
        "repo_root": str(path),
        "workspace_dir": str(workspace_dir),
        "workspace_num": workspace_num,
        "label": safe_label,
        "reason": reason,
        "quarantined_path": str(destination),
        "files": [RESCUE_QUARANTINE_DIRNAME],
        "restore": {
            "quarantine": (
                f"cp -r {destination} <destination>  # quarantined clone copy"
            ),
        },
    }
    manifest_path = rescue_dir / RESCUE_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    record = RescueRecord(
        rescue_dir=rescue_dir,
        manifest_path=manifest_path,
        quarantined_path=destination,
    )
    notify_rescue(record, label=safe_label, reason=reason)
    reap_rescue_store()
    return record


def _reap_rescue_roots(
    *,
    rescue_roots: list[Path] | None = None,
    now: float | None = None,
) -> None:
    roots = rescue_roots if rescue_roots is not None else _all_rescue_roots()
    reference = now if now is not None else time.time()
    for root in roots:
        if root.name == "rescue":
            try:
                if not root.is_dir():
                    continue
                month_dirs = sorted(
                    child
                    for child in root.iterdir()
                    if child.is_dir() and not child.is_symlink()
                )
            except OSError:
                continue
            for month_dir in month_dirs:
                _reap_rescue_entries(month_dir, reference)
        else:
            _reap_rescue_entries(root, reference)


def _reap_rescue_entries(month_dir: Path, now: float) -> None:
    try:
        entries = sorted(
            child
            for child in month_dir.iterdir()
            if child.is_dir() and not child.is_symlink()
        )
    except OSError:
        return
    for entry in entries:
        try:
            age_days = (now - entry.stat().st_mtime) / 86400.0
        except OSError:
            continue
        quarantined = (entry / RESCUE_QUARANTINE_DIRNAME).exists() or os.path.lexists(
            entry / RESCUE_QUARANTINE_DIRNAME
        )
        limit = (
            RESCUE_QUARANTINE_RETENTION_DAYS
            if quarantined
            else RESCUE_ENTRY_RETENTION_DAYS
        )
        if age_days > limit:
            shutil.rmtree(entry, ignore_errors=True)


def _all_rescue_roots() -> list[Path]:
    from sase.core.paths import sase_home, sase_projects_dir

    roots: list[Path] = []
    try:
        projects_dir = sase_projects_dir()
        if projects_dir.is_dir():
            roots.extend(sorted(child / "rescue" for child in projects_dir.iterdir()))
    except OSError:
        pass
    roots.append(sase_home() / "rescue")
    return roots


def _rescue_root_for_workspace(workspace_dir: Path) -> Path:
    project_key = _project_key_for_workspace(workspace_dir)
    if project_key is not None:
        from sase.core.paths import sase_projects_dir

        return sase_projects_dir() / project_key / "rescue"
    from sase.core.paths import sase_home

    return sase_home() / "rescue"


def _project_key_for_workspace(workspace_dir: Path) -> str | None:
    try:
        from sase.bead.project_name import scan_projects_for_cwd
        from sase.core.paths import is_valid_sase_project_name

        scanned = scan_projects_for_cwd(str(workspace_dir))
    except Exception:  # noqa: BLE001 - key resolution must not break rescue.
        return None
    if scanned is None:
        return None
    project_key = scanned[0]
    try:
        if not is_valid_sase_project_name(project_key):
            return None
    except Exception:  # noqa: BLE001 - fail closed to the machine-level store.
        return None
    return project_key


def new_rescue_dir(workspace_dir: Path, entry_name: str) -> Path:
    from sase.sdd._paths import get_yyyymm

    month = get_yyyymm()
    rescue_root = _rescue_root_for_workspace(workspace_dir)
    candidates = [rescue_root / month / entry_name]
    candidates.extend(
        rescue_root / month / f"{entry_name}-{index}" for index in range(1, 100)
    )
    candidates.append(rescue_root / month / f"{entry_name}-{time.time_ns()}")
    for candidate in candidates:
        if (not candidate.exists() and not os.path.lexists(candidate)) and (
            _is_outside_workspace(candidate, workspace_dir)
        ):
            return candidate
    raise RuntimeError(f"no rescue directory available under {rescue_root}")


def _is_outside_workspace(candidate: Path, workspace_dir: Path) -> bool:
    try:
        resolved_candidate = candidate.resolve(strict=False)
        resolved_workspace = workspace_dir.expanduser().resolve(strict=False)
    except OSError:
        return False
    if resolved_candidate == resolved_workspace:
        return False
    return resolved_workspace not in resolved_candidate.parents


def sanitize_label(label: str) -> str:
    cleaned = _LABEL_SAFE_RE.sub("-", label.strip()).strip("-.")
    return cleaned[:64] or "sidecar"


def notify_rescue(record: RescueRecord, *, label: str, reason: str) -> None:
    try:
        from sase.notifications import notify_workflow_complete

        rescued: list[str] = []
        if record.bundle_path is not None:
            rescued.append(f"local commits ({record.bundle_path.name})")
        if record.patch_path is not None:
            rescued.append(f"worktree changes ({record.patch_path.name})")
        if record.quarantined_path is not None:
            rescued.append("the full clone directory")
        if record.note is not None:
            rescued.append(record.note)
        notes = [
            f"Rescued leftover state from {label} before workspace healing: "
            f"{', '.join(rescued) or 'repository state'}.",
            f"Reason: {reason}",
            f"Rescue dir: {record.rescue_dir}",
            "Restore with the commands in manifest.json "
            "(git fetch the bundle, git apply the patch).",
        ]
        notify_workflow_complete(
            "workspace-rescue",
            os.environ.get("SASE_AGENT_CL_NAME", ""),
            True,
            notes,
            extra_files=[str(record.rescue_dir)],
            tags=["sidecar"],
        )
    except Exception:  # noqa: BLE001 - notification failure must not break rescue.
        logger.debug("Failed to report workspace rescue", exc_info=True)
        print(
            f"Warning: rescued {label} to {record.rescue_dir} "
            f"but the rescue notification could not be sent",
            file=sys.stderr,
        )

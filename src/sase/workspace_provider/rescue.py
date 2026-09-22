"""Durable rescue store for launch-time workspace healing.

When a numbered ephemeral workspace holds leftover state an earlier run left
behind (unpublishable sidecar commits, conflicted checkouts), a new launch
must never fail because of it. This module preserves that state *outside* the
workspace on a best-effort basis — git bundles, worktree patches, manifests —
so the workspace itself can be healed or evicted afterwards.

The store lives under ``sase_projects_dir()/<project key>/rescue/<YYYYMM>/``
with a machine-level ``~/.sase/rescue/`` fallback when no project key
resolves, and never inside the workspace directory. Every entry carries a
``manifest.json`` with copy-pasteable restore commands.

All entry points are best-effort and never raise: a rescue that itself fails
warns loudly and lets the launch proceed anyway. Losing an old workspace's
changes is preferred over failing a new launch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, UTC
from pathlib import Path

logger = logging.getLogger(__name__)

RESCUE_SCHEMA_VERSION = 1
RESCUE_BUNDLE_NAME = "local-commits.bundle"
RESCUE_PATCH_NAME = "worktree.patch"
RESCUE_MANIFEST_NAME = "manifest.json"
RESCUE_QUARANTINE_DIRNAME = "quarantined-clone"

#: Cap for the worktree patch (64 MiB). Larger worktrees skip the patch and
#: record a note in the manifest instead.
RESCUE_PATCH_MAX_BYTES = 64 * 1024 * 1024

#: Per-git-call timeout. Rescue runs while the workspace may be contended, so
#: no single git invocation may hang the launch.
RESCUE_GIT_TIMEOUT_SECONDS = 60

#: Retention windows. The disk is heavily used, so quarantined whole-clone
#: copies stay short-lived while bundles/patches linger longer.
RESCUE_ENTRY_RETENTION_DAYS = 30
RESCUE_QUARANTINE_RETENTION_DAYS = 7

#: SHA of the empty git tree, for diffing worktrees whose HEAD is unborn.
_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

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


def rescue_git_repo(
    repo_root: str | Path,
    *,
    workspace_dir: str | Path,
    workspace_num: int,
    label: str,
    reason: str,
    include_worktree: bool,
) -> RescueRecord | None:
    """Bundle local-only commits and the worktree outside the workspace.

    Returns ``None`` when there was nothing to rescue. Never raises.
    """
    try:
        return _rescue_git_repo(
            Path(repo_root),
            workspace_dir=Path(workspace_dir),
            workspace_num=workspace_num,
            label=label,
            reason=reason,
            include_worktree=include_worktree,
        )
    except Exception:  # noqa: BLE001 - rescue must never break a launch.
        logger.warning("Workspace rescue failed for %s", repo_root, exc_info=True)
        return None


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


def _reap_rescue_store(
    *,
    rescue_roots: list[Path] | None = None,
    now: float | None = None,
) -> None:
    """Delete aged rescue entries. Best-effort; never raises."""
    try:
        _reap_rescue_roots(rescue_roots=rescue_roots, now=now)
    except Exception:  # noqa: BLE001 - reaping must never break a launch.
        logger.debug("Rescue store reaping failed", exc_info=True)


def _rescue_git_repo(
    repo_root: Path,
    *,
    workspace_dir: Path,
    workspace_num: int,
    label: str,
    reason: str,
    include_worktree: bool,
) -> RescueRecord | None:
    if not _is_git_repo(repo_root):
        return None
    head = _git(repo_root, "rev-parse", "--verify", "HEAD")
    branch = _git(repo_root, "symbolic-ref", "-q", "--short", "HEAD")
    upstream = _git(repo_root, "rev-parse", "--verify", "@{upstream}")
    status = _git(repo_root, "status", "--porcelain")
    stash_shas = _stash_shas(repo_root)
    has_worktree_changes = bool((status.stdout or "").strip()) or bool(stash_shas)
    if include_worktree is False:
        has_worktree_changes = False

    bundle_refs = _bundle_refs(repo_root, head=head, stash_shas=stash_shas)
    if not bundle_refs and not has_worktree_changes:
        return None

    safe_label = _sanitize_label(label or repo_root.name)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(
        f"{repo_root}|{head.stdout.strip()}|{stamp}".encode()
    ).hexdigest()[:8]
    rescue_dir = _new_rescue_dir(
        workspace_dir,
        f"{stamp}-ws{workspace_num}-{safe_label}-{digest}",
    )
    rescue_dir.mkdir(parents=True, exist_ok=True)

    bundle_path: Path | None = None
    if bundle_refs:
        bundle_path = _write_bundle(repo_root, rescue_dir, bundle_refs)

    patch_path: Path | None = None
    patch_note: str | None = None
    if include_worktree and has_worktree_changes:
        patch_path, patch_note = _write_worktree_patch(
            repo_root, rescue_dir, head_sha=head.stdout.strip() or None
        )

    if (
        bundle_path is None
        and patch_path is None
        and not stash_shas
        and not (status.stdout or "").strip()
    ):
        # Bundling found nothing (e.g. every ref is already remote-reachable)
        # and the worktree is clean: no rescue entry needed.
        shutil.rmtree(rescue_dir, ignore_errors=True)
        return None

    operation_markers = _operation_markers(repo_root)
    files = sorted(
        path.name
        for path in (rescue_dir.glob("*"))
        if path.is_file() and path.name != RESCUE_MANIFEST_NAME
    )
    manifest = {
        "schema_version": RESCUE_SCHEMA_VERSION,
        "timestamp": stamp,
        "repo_root": str(repo_root),
        "workspace_dir": str(workspace_dir),
        "workspace_num": workspace_num,
        "label": safe_label,
        "reason": reason,
        "branch": branch.stdout.strip() or None,
        "head": head.stdout.strip() or None,
        "upstream": upstream.stdout.strip() or None,
        "operation_markers": operation_markers,
        "status_porcelain": status.stdout or "",
        "stash_entries": len(stash_shas),
        "files": files,
        "restore": _restore_commands(
            bundle_path.name if bundle_path else None,
            patch_path.name if patch_path else None,
            stamp,
        ),
    }
    if patch_note is not None:
        manifest["patch_note"] = patch_note
    manifest_path = rescue_dir / RESCUE_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    record = RescueRecord(
        rescue_dir=rescue_dir,
        manifest_path=manifest_path,
        bundle_path=bundle_path,
        patch_path=patch_path,
        note=patch_note,
    )
    _notify_rescue(record, label=safe_label, reason=reason)
    _reap_rescue_store()
    return record


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
    safe_label = _sanitize_label(label or path.name)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(f"{path}|{stamp}".encode()).hexdigest()[:8]
    rescue_dir = _new_rescue_dir(
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
    _notify_rescue(record, label=safe_label, reason=reason)
    _reap_rescue_store()
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


def _new_rescue_dir(workspace_dir: Path, entry_name: str) -> Path:
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


def _sanitize_label(label: str) -> str:
    cleaned = _LABEL_SAFE_RE.sub("-", label.strip()).strip("-.")
    return cleaned[:64] or "sidecar"


def _is_git_repo(repo_root: Path) -> bool:
    result = _git(repo_root, "rev-parse", "--git-dir")
    return result.returncode == 0


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    from sase.workspace_provider._utils_git import non_interactive_git_env

    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
            timeout=RESCUE_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=124,
            stdout="",
            stderr=str(exc),
        )


def _stash_shas(repo_root: Path) -> list[str]:
    result = _git(repo_root, "stash", "list", "--format=%H")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _bundle_refs(
    repo_root: Path, *, head: subprocess.CompletedProcess[str], stash_shas: list[str]
) -> list[str]:
    refs: list[str] = []
    for namespace in ("refs/heads", "refs/tags", "refs/sase/recovery"):
        result = _git(repo_root, "for-each-ref", "--format=%(refname)", namespace)
        if result.returncode == 0:
            refs.extend(
                line.strip() for line in result.stdout.splitlines() if line.strip()
            )
    branch_result = _git(repo_root, "symbolic-ref", "-q", "HEAD")
    if branch_result.returncode != 0 and head.returncode == 0 and head.stdout.strip():
        # Detached HEAD holding commits no branch contains: bundle it by SHA.
        refs.append(head.stdout.strip())
    temp_refs: list[str] = []
    for index, sha in enumerate(stash_shas):
        ref = f"refs/sase/rescue-tmp/stash-{index}"
        created = _git(repo_root, "update-ref", ref, sha)
        if created.returncode == 0:
            temp_refs.append(ref)
    refs.extend(temp_refs)
    return refs


def _write_bundle(repo_root: Path, rescue_dir: Path, refs: list[str]) -> Path | None:
    bundle_path = rescue_dir / RESCUE_BUNDLE_NAME
    temp_refs = [ref for ref in refs if ref.startswith("refs/sase/rescue-tmp/")]
    try:
        remotes = _git(repo_root, "for-each-ref", "--format=%(refname)", "refs/remotes")
        args = ["bundle", "create", str(bundle_path), *refs]
        if remotes.returncode == 0 and remotes.stdout.strip():
            args.extend(["--not", "--remotes"])
        result = _git(repo_root, *args)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if "Refusing to create empty bundle" in detail:
                return None
            logger.warning("Workspace rescue bundle failed: %s", detail)
            return None
        verify = _git(repo_root, "bundle", "verify", str(bundle_path))
        if verify.returncode != 0:
            logger.warning(
                "Workspace rescue bundle failed verification: %s",
                (verify.stderr or verify.stdout or "").strip(),
            )
            return None
        return bundle_path
    finally:
        for ref in temp_refs:
            _git(repo_root, "update-ref", "-d", ref)
        if bundle_path is not None and bundle_path.exists():
            pass
        elif bundle_path is not None and os.path.lexists(bundle_path):
            try:
                bundle_path.unlink()
            except OSError:
                pass


def _write_worktree_patch(
    repo_root: Path, rescue_dir: Path, head_sha: str | None
) -> tuple[Path | None, str | None]:
    patch_path = rescue_dir / RESCUE_PATCH_NAME
    tmp_index = rescue_dir / ".tmp-rescue-index"
    try:
        from sase.workspace_provider._utils_git import non_interactive_git_env

        env = non_interactive_git_env()
        env["GIT_INDEX_FILE"] = str(tmp_index)
        try:
            add = subprocess.run(
                ["git", "add", "-A"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                env=env,
                stdin=subprocess.DEVNULL,
                timeout=RESCUE_GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"worktree patch skipped: git add failed: {exc}"
        if add.returncode != 0:
            return None, (
                "worktree patch skipped: "
                f"{(add.stderr or add.stdout or '').strip() or 'git add failed'}"
            )
        base = head_sha or _EMPTY_TREE_SHA
        try:
            diff = subprocess.run(
                ["git", "diff", "--cached", "--binary", base],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                env=env,
                stdin=subprocess.DEVNULL,
                timeout=RESCUE_GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"worktree patch skipped: git diff failed: {exc}"
        if diff.returncode != 0:
            return None, (
                "worktree patch skipped: "
                f"{(diff.stderr or diff.stdout or '').strip() or 'git diff failed'}"
            )
        content = diff.stdout or ""
        if not content.strip():
            return None, None
        if len(content.encode("utf-8")) > RESCUE_PATCH_MAX_BYTES:
            return None, (
                f"worktree patch skipped: {len(content.encode('utf-8'))} bytes "
                f"exceeds the {RESCUE_PATCH_MAX_BYTES}-byte cap"
            )
        patch_path.write_text(content, encoding="utf-8")
        return patch_path, None
    finally:
        try:
            tmp_index.unlink(missing_ok=True)
        except OSError:
            pass


def _operation_markers(repo_root: Path) -> list[str]:
    git_dir_result = _git(repo_root, "rev-parse", "--absolute-git-dir")
    markers: list[str] = []
    if git_dir_result.returncode != 0 or not git_dir_result.stdout.strip():
        return markers
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    dir_markers = (
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    )
    file_markers = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_LOG",
        "BISECT_EXPECTED_REV",
    )
    for name in dir_markers:
        if (git_dir / name).is_dir():
            markers.append(name)
    for name in file_markers:
        if (git_dir / name).is_file():
            markers.append(name)
    return sorted(markers)


def _restore_commands(
    bundle_name: str | None, patch_name: str | None, stamp: str
) -> dict[str, str]:
    commands: dict[str, str] = {}
    if bundle_name is not None:
        commands["bundle"] = (
            f"git fetch <rescue-dir>/{bundle_name} 'refs/*:refs/sase/rescued/{stamp}/*'"
        )
    if patch_name is not None:
        commands["patch"] = f"git apply --index <rescue-dir>/{patch_name}"
    return commands


def _notify_rescue(record: RescueRecord, *, label: str, reason: str) -> None:
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

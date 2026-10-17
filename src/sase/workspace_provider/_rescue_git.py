"""Git history preservation for workspace rescue."""

from __future__ import annotations


import hashlib

import json

import logging

import os

import shutil

import subprocess

from dataclasses import dataclass

from datetime import UTC, datetime

from pathlib import Path


from sase.workspace_provider._rescue_git_commands import (
    run_git,
)

from sase.workspace_provider._rescue_git_worktree import write_worktree_patch

from sase.workspace_provider._rescue_store import (
    RESCUE_MANIFEST_NAME,
    RESCUE_SCHEMA_VERSION,
    RescueRecord,
    new_rescue_dir,
    notify_rescue,
    reap_rescue_store,
    sanitize_label,
)


logger = logging.getLogger(__name__)


RESCUE_BUNDLE_NAME = "local-commits.bundle"


@dataclass(frozen=True)
class _WorkRefs:
    """Work anchors and tag labels collected from a clone.

    Tags never trigger a rescue on their own. They only ride along as
    labels for commits that an anchor is already being rescued for. A
    tag whose commit nothing else references (no branch, stash, recovery
    ref, or detached HEAD ahead of every tag) is not rescued. This
    extends the trade-off :func:`_published_tags` already accepts for
    never-pushed tags on pushed commits.
    """

    branch_anchors: tuple[str, ...]
    tags: tuple[str, ...]
    detached_head_sha: str | None
    stash_shas: tuple[str, ...]

    def all_anchors(self) -> list[str]:
        anchors = list(self.branch_anchors)
        if self.detached_head_sha is not None:
            anchors.append(self.detached_head_sha)
        anchors.extend(self.stash_shas)
        return anchors


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
    Tags never trigger a rescue on their own.
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
    try:
        return _rescue_git_repo_body(
            repo_root,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            label=label,
            reason=reason,
            include_worktree=include_worktree,
        )
    finally:
        _delete_rescue_tmp_namespace(repo_root)


def _rescue_git_repo_body(
    repo_root: Path,
    *,
    workspace_dir: Path,
    workspace_num: int,
    label: str,
    reason: str,
    include_worktree: bool,
) -> RescueRecord | None:
    head = run_git(repo_root, "rev-parse", "--verify", "HEAD")
    branch = run_git(repo_root, "symbolic-ref", "-q", "--short", "HEAD")
    upstream = run_git(repo_root, "rev-parse", "--verify", "@{upstream}")
    status = run_git(repo_root, "status", "--porcelain")
    stash_shas = _stash_shas(repo_root)
    has_worktree_changes = bool((status.stdout or "").strip()) or bool(stash_shas)
    if include_worktree is False:
        has_worktree_changes = False

    collected = _collect_work_refs(repo_root, head=head, stash_shas=stash_shas)
    needs_bundle = _anchors_need_bundle(repo_root, collected.all_anchors())
    if not needs_bundle and not has_worktree_changes:
        return None

    safe_label = sanitize_label(label or repo_root.name)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(
        f"{repo_root}|{head.stdout.strip()}|{stamp}".encode()
    ).hexdigest()[:8]
    rescue_dir = new_rescue_dir(
        workspace_dir,
        f"{stamp}-ws{workspace_num}-{safe_label}-{digest}",
    )
    rescue_dir.mkdir(parents=True, exist_ok=True)

    bundle_path: Path | None = None
    if needs_bundle:
        bundle_refs, _ = _prepare_bundle_refs(repo_root, collected)
        bundle_path = _write_bundle(repo_root, rescue_dir, bundle_refs)

    patch_path: Path | None = None
    patch_note: str | None = None
    if include_worktree and has_worktree_changes:
        patch_path, patch_note = write_worktree_patch(
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
    notify_rescue(record, label=safe_label, reason=reason)
    reap_rescue_store()
    return record


def _is_git_repo(repo_root: Path) -> bool:
    result = run_git(repo_root, "rev-parse", "--git-dir")
    return result.returncode == 0


def _stash_shas(repo_root: Path) -> list[str]:
    result = run_git(repo_root, "stash", "list", "--format=%H")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _refnames(repo_root: Path, namespace: str) -> list[str]:
    result = run_git(repo_root, "for-each-ref", "--format=%(refname)", namespace)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _remote_tracking_refs(repo_root: Path) -> list[str]:
    return _refnames(repo_root, "refs/remotes")


def _tags_merged_into(repo_root: Path, commits: list[str]) -> set[str]:
    """Tags whose commit is reachable from at least one of *commits*."""
    if not commits:
        return set()
    args = ["for-each-ref", "--format=%(refname)"]
    args.extend(f"--merged={ref}" for ref in commits)
    args.append("refs/tags")
    result = run_git(repo_root, *args)
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _published_tags(repo_root: Path, remote_refs: list[str]) -> set[str]:
    """Tags whose commit is reachable from a remote-tracking ref.

    `git bundle ... --not --remotes` always writes non-commit tips, so
    annotated tags become bundle heads even when their commit is pushed.
    Git keeps no list of which tags a remote has, and rescue must stay
    offline (no `git ls-remote` during launch), so a never-pushed tag on a
    pushed commit is not rescued; only the tag name and message are lost,
    never a commit. Tags also never trigger a rescue on their own: a tag
    whose commit nothing else references is not rescued. With no
    remote-tracking refs, keep every tag, matching `_write_bundle()`, which
    then bundles everything.
    """
    if not remote_refs:
        return set()
    return _tags_merged_into(repo_root, remote_refs)


def _unpublished_detached_head_sha(
    repo_root: Path, *, head: subprocess.CompletedProcess[str]
) -> str | None:
    """Return HEAD when a detached checkout holds commits not on remotes or tags.

    A detached HEAD resting on, or behind, a tag checkout (``git checkout
    <tag>``) is not local work: ``git rev-list -1 HEAD --not --remotes
    --tags`` is empty. A new commit on top of that tag is still rescued.
    """
    sha = (head.stdout or "").strip()
    if head.returncode != 0 or not sha:
        return None
    attached = run_git(repo_root, "symbolic-ref", "-q", "HEAD")
    if attached.returncode == 0:
        return None
    unpublished = run_git(
        repo_root, "rev-list", "-1", "HEAD", "--not", "--remotes", "--tags"
    )
    if unpublished.returncode != 0:
        return sha
    if not (unpublished.stdout or "").strip():
        return None
    return sha


def _collect_work_refs(
    repo_root: Path,
    *,
    head: subprocess.CompletedProcess[str],
    stash_shas: list[str],
) -> _WorkRefs:
    """Collect work anchors and tags. Does not create temp refs."""
    branch_anchors = [
        *_refnames(repo_root, "refs/heads"),
        *_refnames(repo_root, "refs/sase/recovery"),
    ]
    tags = _refnames(repo_root, "refs/tags")
    return _WorkRefs(
        branch_anchors=tuple(branch_anchors),
        tags=tuple(tags),
        detached_head_sha=_unpublished_detached_head_sha(repo_root, head=head),
        stash_shas=tuple(stash_shas),
    )


def _anchors_need_bundle(repo_root: Path, anchors: list[str]) -> bool:
    """True when *anchors* carry a commit not reachable from remotes.

    With no remote-tracking refs, any anchor counts. Tags are never
    consulted: they do not trigger a rescue on their own.
    """
    if not anchors:
        return False
    if not _remote_tracking_refs(repo_root):
        return True
    result = run_git(repo_root, "rev-list", "-1", *anchors, "--not", "--remotes")
    if result.returncode != 0:
        return True
    return bool((result.stdout or "").strip())


def _tags_to_bundle(
    repo_root: Path,
    *,
    anchors: list[str],
    tags: tuple[str, ...],
    remote_refs: list[str],
) -> list[str]:
    """Tags that label rescued work, or every tag when there are no remotes."""
    if not tags:
        return []
    if not remote_refs:
        return list(tags)
    published = _published_tags(repo_root, remote_refs)
    labeled = _tags_merged_into(repo_root, anchors)
    return [tag for tag in tags if tag in labeled and tag not in published]


def _prepare_bundle_refs(
    repo_root: Path, collected: _WorkRefs
) -> tuple[list[str], list[str]]:
    """Return ``(bundle refs, temp refs)``. Creates ``refs/sase/rescue-tmp/``."""
    refs = list(collected.branch_anchors)
    temp_refs: list[str] = []
    if collected.detached_head_sha is not None:
        # Detached HEAD holding commits no branch contains: bundle it through
        # a temporary ref, since `git bundle create` refuses a bare SHA with
        # "Refusing to create empty bundle".
        ref = "refs/sase/rescue-tmp/detached-head"
        created = run_git(repo_root, "update-ref", ref, collected.detached_head_sha)
        if created.returncode == 0:
            temp_refs.append(ref)
        else:
            refs.append(collected.detached_head_sha)
    for index, sha in enumerate(collected.stash_shas):
        ref = f"refs/sase/rescue-tmp/stash-{index}"
        created = run_git(repo_root, "update-ref", ref, sha)
        if created.returncode == 0:
            temp_refs.append(ref)
    refs.extend(temp_refs)
    refs.extend(
        _tags_to_bundle(
            repo_root,
            anchors=collected.all_anchors(),
            tags=collected.tags,
            remote_refs=_remote_tracking_refs(repo_root),
        )
    )
    return refs, temp_refs


def _delete_temp_refs(repo_root: Path, refs: list[str]) -> None:
    for ref in refs:
        run_git(repo_root, "update-ref", "-d", ref)


def _delete_rescue_tmp_namespace(repo_root: Path) -> None:
    _delete_temp_refs(repo_root, _refnames(repo_root, "refs/sase/rescue-tmp"))


def _write_bundle(repo_root: Path, rescue_dir: Path, refs: list[str]) -> Path | None:
    bundle_path = rescue_dir / RESCUE_BUNDLE_NAME
    temp_refs = [ref for ref in refs if ref.startswith("refs/sase/rescue-tmp/")]
    try:
        args = ["bundle", "create", str(bundle_path), *refs]
        if _remote_tracking_refs(repo_root):
            args.extend(["--not", "--remotes"])
        result = run_git(repo_root, *args)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if "Refusing to create empty bundle" in detail:
                return None
            logger.warning("Workspace rescue bundle failed: %s", detail)
            return None
        verify = run_git(repo_root, "bundle", "verify", str(bundle_path))
        if verify.returncode != 0:
            logger.warning(
                "Workspace rescue bundle failed verification: %s",
                (verify.stderr or verify.stdout or "").strip(),
            )
            return None
        return bundle_path
    finally:
        _delete_temp_refs(repo_root, temp_refs)
        if bundle_path is not None and bundle_path.exists():
            pass
        elif bundle_path is not None and os.path.lexists(bundle_path):
            try:
                bundle_path.unlink()
            except OSError:
                pass


def _operation_markers(repo_root: Path) -> list[str]:
    git_dir_result = run_git(repo_root, "rev-parse", "--absolute-git-dir")
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

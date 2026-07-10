"""Lossless adoption helpers for provider-owned companion SDD stores."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import filecmp
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from sase.sdd._bead_ignore import BEAD_STORE_GITIGNORE_PATTERNS
from sase.sdd._store_types import SddMaterializationError, SddStoreRecord

_RUNTIME_ONLY_PATHS = frozenset(BEAD_STORE_GITIGNORE_PATTERNS)


@contextmanager
def materialization_lock(primary: Path) -> Iterator[None]:
    """Serialize the primary companion create/adopt transaction."""

    lock_path = primary / ".sase" / "sdd-materialize.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def new_staging_path(primary: Path) -> Path:
    """Return a unique, not-yet-created staging path beside the primary store."""

    return primary / ".sase" / f".sdd.materialize-{os.getpid()}-{uuid.uuid4().hex}"


def clone_matches_record(path: Path, record: SddStoreRecord) -> bool:
    """Return whether *path* is an adoptable clone for *record*."""

    if not (path / ".git").is_dir():
        return False
    if not record.remote_url:
        return True
    origin = _git_stdout(path, ["remote", "get-url", "origin"])
    return origin is not None and _normalize_remote(origin) == _normalize_remote(
        record.remote_url
    )


def adopt_provider_store(
    primary: Path,
    workspace: Path,
    record: SddStoreRecord,
    staging: Path,
) -> Path:
    """Stage, merge, push, and atomically adopt a companion checkout.

    Local and in-tree sources are never mutated. The primary path is replaced only
    after every import has passed conflict checks and the staged commit has pushed.
    """

    target = primary / ".sase" / "sdd"
    sources = _legacy_sources(primary, workspace, target, record)
    try:
        _ensure_staging_clone(staging, target, record)
        conflicts = _merge_conflicts(sources, staging)
        if conflicts:
            rendered = "\n  - ".join(conflicts)
            raise SddMaterializationError(
                "legacy SDD artifacts conflict with the companion repository:\n"
                f"  - {rendered}\n"
                "No source files were changed. Reconcile these paths and rerun "
                "`sase sdd init`."
            )
        for source in sources:
            _copy_durable_artifacts(source, staging)
        _bootstrap_and_push(staging)
        _replace_primary_store(target, staging)
        return target
    except SddMaterializationError:
        raise
    except Exception as exc:  # noqa: BLE001 - transaction failures are user-facing.
        detail = str(exc) or type(exc).__name__
        raise SddMaterializationError(
            f"could not adopt the companion SDD repository: {detail}"
        ) from exc


def cleanup_staging(path: Path) -> None:
    """Remove an unused staging checkout without touching adopted paths."""

    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                path.unlink()
            except OSError:
                pass


def has_durable_artifacts(path: Path) -> bool:
    """Return whether a legacy SDD source contains importable artifacts."""

    return any(_iter_durable_files(path))


def legacy_adoption_needed(
    primary: Path,
    workspace: Path,
    record: SddStoreRecord,
) -> bool:
    """Return whether a retained legacy source differs from the companion."""

    target = primary / ".sase" / "sdd"
    for source in _legacy_sources(primary, workspace, target, record):
        for item in _iter_durable_files(source):
            destination = target / item.relative_to(source)
            if not (destination.exists() or destination.is_symlink()):
                return True
            if not _same_artifact(item, destination):
                return True
    return False


def _legacy_sources(
    primary: Path,
    workspace: Path,
    target: Path,
    record: SddStoreRecord,
) -> list[Path]:
    candidates = [target, primary / "sdd"]
    workspace_local = workspace / ".sase" / "sdd"
    workspace_in_tree = workspace / "sdd"
    candidates.extend((workspace_local, workspace_in_tree))

    sources: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        normalized = candidate.resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate == target and clone_matches_record(candidate, record):
            continue
        if candidate == workspace_local and clone_matches_record(candidate, record):
            continue
        if has_durable_artifacts(candidate):
            sources.append(candidate)
    return sources


def _ensure_staging_clone(
    staging: Path,
    target: Path,
    record: SddStoreRecord,
) -> None:
    if clone_matches_record(staging, record):
        return
    cleanup_staging(staging)
    staging.parent.mkdir(parents=True, exist_ok=True)

    source = str(target) if clone_matches_record(target, record) else record.remote_url
    if not source:
        raise SddMaterializationError(
            "provider returned a companion record without a clone URL"
        )
    result = _run_git(
        ["clone", source, str(staging)],
        cwd=staging.parent,
        op="sdd.materialize.clone",
        network=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SddMaterializationError(
            detail or f"git clone failed with exit code {result.returncode}"
        )
    if record.remote_url:
        current = _git_stdout(staging, ["remote", "get-url", "origin"])
        command = (
            ["remote", "set-url", "origin", record.remote_url]
            if current
            else ["remote", "add", "origin", record.remote_url]
        )
        _run_git_checked(command, cwd=staging, op="sdd.materialize.origin")


def _merge_conflicts(sources: list[Path], target: Path) -> list[str]:
    conflicts: set[str] = set()
    accepted: dict[str, Path] = {}
    for source in sources:
        for item in _iter_durable_files(source):
            rel = item.relative_to(source).as_posix()
            existing_source = accepted.get(rel)
            destination = target / rel
            if existing_source is not None and not _same_artifact(
                existing_source, item
            ):
                conflicts.add(rel)
                continue
            accepted.setdefault(rel, item)
            if (
                destination.exists() or destination.is_symlink()
            ) and not _same_artifact(item, destination):
                conflicts.add(rel)
    return sorted(conflicts)


def _copy_durable_artifacts(source: Path, target: Path) -> None:
    for item in _iter_durable_files(source):
        rel = item.relative_to(source)
        destination = target / rel
        if destination.exists() or destination.is_symlink():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if item.is_symlink():
            destination.symlink_to(os.readlink(item))
        else:
            shutil.copy2(item, destination)


def _iter_durable_files(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name != ".git"]
        current_path = Path(current)
        for name in files:
            item = current_path / name
            rel = item.relative_to(root).as_posix()
            if rel in _RUNTIME_ONLY_PATHS or rel.startswith(".git/"):
                continue
            yield item
        for name in tuple(dirs):
            item = current_path / name
            if item.is_symlink():
                dirs.remove(name)
                yield item


def _same_artifact(left: Path, right: Path) -> bool:
    if left.is_symlink() or right.is_symlink():
        return (
            left.is_symlink()
            and right.is_symlink()
            and os.readlink(left) == os.readlink(right)
        )
    if not left.is_file() or not right.is_file():
        return False
    try:
        return filecmp.cmp(left, right, shallow=False)
    except OSError:
        return False


def _bootstrap_and_push(repo: Path) -> None:
    from sase.bead.project import BEADS_DIRNAME_NON_VC, BeadProject
    from sase.sdd._bead_ignore import ensure_bead_store_gitignore
    from sase.sdd._commit import commit_sdd_files
    from sase.sdd.files import ensure_sdd_initialized

    ensure_sdd_initialized(repo)
    ensure_bead_store_gitignore(repo)
    beads_dir = repo / BEADS_DIRNAME_NON_VC
    if not beads_dir.is_dir():
        with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME_NON_VC):
            pass

    committed = commit_sdd_files(
        repo,
        "Initialize or import SDD companion store",
        auto_commit_type="sdd",
        paths=None,
        record_commit_marker=False,
    )
    if not committed:
        return
    _push_companion_store(repo)


def _push_companion_store(repo: Path) -> None:
    """Push the companion commit, integrating concurrent remote work first.

    Many workspaces materialize the same shared companion repository, so a
    non-fast-forward rejection is expected whenever another materialization (or
    an ordinary SDD push) advanced the remote between our clone and this push.
    Mirror the established bead-sync idiom -- push, and on rejection
    ``git pull --rebase`` then retry -- instead of aborting the whole setup
    transaction on the first rejection. The primary store is still only replaced
    after the staged commit has landed on the remote.
    """

    result = _run_git(
        ["push", "-u", "origin", "HEAD"],
        cwd=repo,
        op="sdd.materialize.push",
        network=True,
    )
    if result.returncode == 0:
        return

    push_detail = (result.stderr or result.stdout or "").strip()
    rebase = _run_git(
        ["pull", "--rebase"],
        cwd=repo,
        op="sdd.materialize.pull_rebase",
        network=True,
    )
    if rebase.returncode != 0:
        rebase_detail = (rebase.stderr or rebase.stdout or "").strip()
        raise SddMaterializationError(
            rebase_detail
            or push_detail
            or f"git push failed with exit code {result.returncode}"
        )

    retry = _run_git(
        ["push", "-u", "origin", "HEAD"],
        cwd=repo,
        op="sdd.materialize.push",
        network=True,
    )
    if retry.returncode != 0:
        detail = (retry.stderr or retry.stdout or push_detail or "").strip()
        raise SddMaterializationError(
            detail or f"git push failed with exit code {retry.returncode}"
        )


def _replace_primary_store(target: Path, staging: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(f".sdd.recovery-{uuid.uuid4().hex}")
    had_target = target.exists() or target.is_symlink()
    if had_target:
        target.replace(backup)
    try:
        staging.replace(target)
    except Exception:
        if had_target and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    if had_target:
        cleanup_staging(backup)


def _git_stdout(cwd: Path, args: list[str]) -> str | None:
    result = _run_git(args, cwd=cwd, op="sdd.materialize.inspect", network=False)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _run_git_checked(args: list[str], *, cwd: Path, op: str) -> None:
    result = _run_git(args, cwd=cwd, op=op, network=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SddMaterializationError(
            detail or f"git {' '.join(args)} failed with exit code {result.returncode}"
        )


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    op: str,
    network: bool,
) -> subprocess.CompletedProcess[str]:
    from sase.sdd._commit import network_git_timeout, run_sdd_git

    return run_sdd_git(
        args,
        cwd=cwd,
        op=op,
        timeout=network_git_timeout() if network else None,
        check=False,
        capture_output=True,
        text=True,
    )


def _normalize_remote(value: str) -> str:
    normalized = value.strip().rstrip("/")
    return normalized[:-4] if normalized.endswith(".git") else normalized

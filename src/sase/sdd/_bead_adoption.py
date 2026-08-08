"""Record-last adoption of plans-owned state into a beads sidecar."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import subprocess

from sase.sdd._bead_ignore import bead_store_gitignore_patterns
from sase.sdd._bead_state import has_bead_state
from sase.sdd._commit import commit_sdd_files, run_sdd_git
from sase.sdd._sidecar_git import push_sidecar
from sase.sdd._store_types import SddMaterializationError

_BEAD_CACHE_FILENAMES = frozenset(
    {
        "beads.db",
        "beads.db-shm",
        "beads.db-wal",
        ".bead-mutation-lock.holder",
    }
)
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdoptionOutcome:
    """Result of attempting to import plans-owned bead state."""

    adopted: bool
    source_present: bool


def adopt_bead_state(
    plans_root: Path,
    beads_root: Path,
    *,
    plans_repo: str | None = None,
    publish_changes: bool = True,
) -> AdoptionOutcome:
    """Import a plans-embedded bead store into the beads sidecar and push it.

    The store record is intentionally not touched here. Callers may only write
    the schema-3 switch after this function returns successfully.
    """

    source = plans_root / "beads"
    if not source.is_dir():
        return AdoptionOutcome(adopted=False, source_present=False)

    if has_bead_state(beads_root):
        # This is either an ordinary rerun or recovery after the import commit
        # succeeded locally but its push failed. Commit any interrupted copy,
        # then make the push a precondition of the record switch.
        source_paths = tuple(
            beads_root / entry.name
            for entry in source.iterdir()
            if entry.name not in _BEAD_CACHE_FILENAMES
        )
        committed = False
        if publish_changes:
            committed = _commit_imported_bead_state(
                plans_root,
                beads_root,
                plans_repo=plans_repo,
                paths=source_paths,
            )
            push_sidecar(beads_root)
        return AdoptionOutcome(adopted=committed, source_present=True)

    copied = _copy_bead_state(source, beads_root)
    committed = False
    if publish_changes:
        committed = _commit_imported_bead_state(
            plans_root,
            beads_root,
            plans_repo=plans_repo,
            paths=copied,
        )
        if committed:
            push_sidecar(beads_root)
    return AdoptionOutcome(adopted=committed, source_present=True)


def cleanup_plans_bead_state(
    plans_root: Path,
    *,
    publish_changes: bool = True,
) -> None:
    """Best-effort removal after the schema-3 record becomes authoritative."""

    try:
        source = plans_root / "beads"
        if source.exists() or source.is_symlink():
            if source.is_dir() and not source.is_symlink():
                shutil.rmtree(source)
            else:
                source.unlink()
        gitignore = _drop_plans_bead_ignores(plans_root)
        paths: list[Path] = [source]
        if gitignore is not None:
            paths.append(gitignore)
        if publish_changes:
            commit_sdd_files(
                plans_root,
                "Move bead state to the beads sidecar",
                auto_commit_type="beads",
                paths=paths,
                record_commit_marker=False,
            )
            # Push even when there was no new commit: a previous run may have
            # committed cleanup locally and failed during its best-effort push.
            push_sidecar(plans_root)
    except Exception as exc:  # noqa: BLE001 - post-switch cleanup is best effort.
        _logger.warning(
            "bead state now resolves to the beads sidecar, but plans-side "
            "cleanup failed and will be retried by `sase repo init`: %s",
            exc,
        )


def _copy_bead_state(source: Path, target: Path) -> tuple[Path, ...]:
    copied: list[Path] = []
    for entry in source.iterdir():
        if entry.name in _BEAD_CACHE_FILENAMES:
            continue
        destination = target / entry.name
        if entry.is_symlink():
            if destination.exists() or destination.is_symlink():
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            destination.symlink_to(os.readlink(entry))
        elif entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True, symlinks=True)
        else:
            shutil.copy2(entry, destination)
        copied.append(destination)
    return tuple(copied)


def _commit_imported_bead_state(
    plans_root: Path,
    beads_root: Path,
    *,
    plans_repo: str | None,
    paths: Sequence[Path] | None = None,
) -> bool:
    source_repo = plans_repo or _git_repo_label(plans_root)
    source_sha = _git_short_head(plans_root)
    return commit_sdd_files(
        beads_root,
        f"Import bead state from {source_repo}@{source_sha}",
        auto_commit_type="beads",
        paths=paths,
        repo_name=source_repo,
        record_commit_marker=False,
    )


def _git_repo_label(root: Path) -> str:
    try:
        result = run_sdd_git(
            ["remote", "get-url", "origin"],
            cwd=root,
            op="sdd.sidecar_init.source_remote",
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return root.name
    raw = result.stdout.strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    if "://" in raw:
        raw = raw.partition("://")[2].partition("/")[2]
    elif ":" in raw and not raw.startswith(("/", ".")):
        raw = raw.rsplit(":", 1)[1]
    parts = [part for part in raw.split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else root.name


def _git_short_head(root: Path) -> str:
    try:
        result = run_sdd_git(
            ["rev-parse", "--short=12", "HEAD"],
            cwd=root,
            op="sdd.sidecar_init.source_head",
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SddMaterializationError(
            f"could not resolve plans sidecar HEAD at {root}: {exc}"
        ) from exc
    return result.stdout.strip()


def _drop_plans_bead_ignores(plans_root: Path) -> Path | None:
    gitignore = plans_root / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    patterns = frozenset(bead_store_gitignore_patterns("beads"))
    lines = existing.splitlines()
    kept = [line for line in lines if line.strip() not in patterns]
    if len(kept) == len(lines):
        return None
    if kept:
        gitignore.write_text("\n".join(kept) + "\n", encoding="utf-8")
    else:
        gitignore.unlink()
    return gitignore

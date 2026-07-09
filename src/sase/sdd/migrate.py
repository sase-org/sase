"""Migration helpers for companion SDD repositories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

from sase.sdd._commit import git_toplevel, network_git_timeout, run_sdd_git
from sase.sdd._init_files import ensure_sdd_initialized
from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd.store import (
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_SEPARATE_REPO,
    SddStore,
    SddStoreRecord,
    normalize_sdd_store_record,
    read_sdd_store_record,
    resolve_sdd_store,
    write_sdd_store_record,
)


class SddMigrationError(RuntimeError):
    """Raised when ``sase sdd migrate`` cannot complete safely."""


@dataclass(frozen=True)
class _SddMigrationResult:
    """Summary of a completed SDD migration."""

    source_storage: str
    sdd_dir: Path
    record: SddStoreRecord
    config_path: Path
    committed: bool
    pushed: bool
    removed_in_tree: bool


def migrate_sdd_to_separate_repo(
    project_root: str | Path,
    *,
    workspace_num: int = 1,
    create: bool = False,
    remove_in_tree: bool = False,
) -> _SddMigrationResult:
    """Migrate the project SDD store to a provider companion repository."""

    root = Path(project_root).expanduser().resolve()
    primary = Path(get_primary_workspace_dir(str(root), workspace_num)).resolve()
    source_store = resolve_sdd_store(root, workspace_num)
    record = _resolve_remote_record(primary, root, workspace_num, create=create)
    if record.discovery == "not_found":
        raise SddMigrationError(
            f"SDD companion repository {record.repo or '<unknown>'} was not found. "
            "Re-run with `sase sdd migrate --create` to create it."
        )
    if not record.remote_url:
        raise SddMigrationError("provider did not return an SDD remote URL")

    sdd_dir = primary / ".sase" / "sdd"
    if source_store.storage == SDD_STORAGE_IN_TREE:
        _copy_in_tree_sdd(root / "sdd", sdd_dir)
    else:
        sdd_dir.mkdir(parents=True, exist_ok=True)

    _ensure_git_repo(sdd_dir)
    _ensure_origin_remote(sdd_dir, record.remote_url)
    record = write_sdd_store_record(primary, record)

    initialized_paths = list(ensure_sdd_initialized(sdd_dir))
    initialized_paths.extend(_ensure_bead_store_initialized(sdd_dir))
    store = SddStore(
        storage=SDD_STORAGE_SEPARATE_REPO,
        sdd_dir=sdd_dir,
        repo_root=sdd_dir,
        provider=record.provider,
        remote_url=record.remote_url,
    )

    from sase.sdd._commit import commit_sdd_store_files

    committed = commit_sdd_store_files(
        store,
        "Migrate SDD to separate repository",
        auto_commit_type="sdd",
        paths=None,
        push_after_commit=False,
    )
    pushed = _push_with_upstream(sdd_dir)

    from sase.main.sdd_init_config import write_sdd_init_config

    config_path = write_sdd_init_config(root, storage=SDD_STORAGE_SEPARATE_REPO)
    removed = _remove_in_tree_sdd(root) if remove_in_tree else False
    return _SddMigrationResult(
        source_storage=source_store.storage,
        sdd_dir=sdd_dir,
        record=record,
        config_path=config_path,
        committed=committed or bool(initialized_paths),
        pushed=pushed,
        removed_in_tree=removed,
    )


def _resolve_remote_record(
    primary: Path,
    workspace: Path,
    workspace_num: int,
    *,
    create: bool,
) -> SddStoreRecord:
    existing = read_sdd_store_record(primary)
    if existing is not None and existing.discovery != "not_found":
        return existing

    try:
        from sase.workspace_provider import create_sdd_remote

        result = create_sdd_remote(
            str(primary),
            str(workspace),
            {
                "workspace_num": workspace_num,
                "create": create,
            },
        )
    except Exception as exc:  # noqa: BLE001 - surface provider failures clearly.
        raise SddMigrationError(str(exc) or type(exc).__name__) from exc

    if result is None:
        raise SddMigrationError(
            "no workspace provider could verify an SDD companion repository"
        )
    return normalize_sdd_store_record(_record_mapping(result))


def _record_mapping(result: dict[str, object] | Any) -> dict[str, object]:
    if not isinstance(result, dict):
        raise SddMigrationError("provider returned an invalid SDD store record")
    return result


def _copy_in_tree_sdd(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise SddMigrationError(f"in-tree SDD directory does not exist: {source}")
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name == ".git":
            continue
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def _ensure_git_repo(path: Path) -> None:
    if (path / ".git").is_dir():
        return
    path.mkdir(parents=True, exist_ok=True)
    run_sdd_git(
        ["init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        op="sdd_migrate.init",
    )


def _ensure_origin_remote(repo: Path, remote_url: str) -> None:
    existing = _origin_remote(repo)
    if existing == remote_url:
        return
    if existing:
        raise SddMigrationError(
            f"SDD store already has a different origin remote: {existing}"
        )
    run_sdd_git(
        ["remote", "add", "origin", remote_url],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        op="sdd_migrate.remote_add",
    )


def _origin_remote(repo: Path) -> str | None:
    result = run_sdd_git(
        ["config", "--get", "remote.origin.url"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        op="sdd_migrate.remote_get",
    )
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _ensure_bead_store_initialized(sdd_dir: Path) -> list[Path]:
    from sase.bead.project import BEADS_DIRNAME_NON_VC, BeadProject
    from sase.sdd._bead_ignore import ensure_bead_store_gitignore

    changed: list[Path] = []
    gitignore = ensure_bead_store_gitignore(sdd_dir)
    if gitignore is not None:
        changed.append(gitignore)

    beads_dir = sdd_dir / BEADS_DIRNAME_NON_VC
    if not beads_dir.is_dir():
        BeadProject.init(sdd_dir, beads_dirname=BEADS_DIRNAME_NON_VC)
        changed.append(beads_dir)
    return changed


def _push_with_upstream(repo: Path) -> bool:
    result = run_sdd_git(
        ["push", "-u", "origin", "HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        timeout=network_git_timeout(),
        op="sdd_migrate.push",
    )
    if result.returncode == 0:
        return True
    detail = (result.stderr or result.stdout or "").strip()
    raise SddMigrationError(
        detail or f"git push failed with exit code {result.returncode}"
    )


def _remove_in_tree_sdd(project_root: Path) -> bool:
    source = project_root / "sdd"
    if not source.exists():
        return False

    git_root = git_toplevel(project_root)
    if git_root is None:
        raise SddMigrationError("cannot remove in-tree SDD: project is not a git repo")
    if source.resolve(strict=False).parent != git_root.resolve(strict=False):
        raise SddMigrationError("cannot remove in-tree SDD outside git root")

    run_sdd_git(
        ["rm", "-r", "--ignore-unmatch", "--", "sdd"],
        cwd=git_root,
        check=True,
        capture_output=True,
        text=True,
        op="sdd_migrate.remove_in_tree",
    )
    diff = run_sdd_git(
        ["diff", "--cached", "--quiet", "--", "sdd"],
        cwd=git_root,
        check=False,
        capture_output=True,
        text=True,
        op="sdd_migrate.remove_in_tree_diff",
    )
    if diff.returncode == 0:
        return False
    if diff.returncode != 1:
        detail = (diff.stderr or diff.stdout or "").strip()
        raise SddMigrationError(detail or "git diff failed for removed SDD files")

    from sase.workflows.commit.runtime_tags import apply_auto_commit_tags_with_runtime

    message = apply_auto_commit_tags_with_runtime(
        "Remove migrated in-tree SDD files",
        "sdd",
    )
    run_sdd_git(
        ["commit", "-m", message, "--", "sdd"],
        cwd=git_root,
        check=True,
        capture_output=True,
        text=True,
        op="sdd_migrate.remove_in_tree_commit",
    )
    return True

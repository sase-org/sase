"""Handler implementation for the ``sase workspace`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.config.core import load_merged_config
from sase.core.paths import is_valid_sase_project_name
from sase.core.project_lifecycle_facade import (
    apply_project_lifecycle_update,
    read_project_lifecycle_from_content,
)
from sase.running_field._operations import get_claimed_workspaces
from sase.workflows.utils import get_project_file_path
from sase.workspace_provider.registry import (
    WorkspaceEntry,
    WorkspaceRegistry,
    load_or_init_registry,
    save_registry,
)
from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WorkspaceStore,
)
from sase.workspace_provider.utils import (
    ensure_workspace_checkout,
    parse_bare_repo_dir,
    parse_workspace_dir,
)


@dataclass(frozen=True)
class _ProjectContext:
    """Cached resolution of a project name to its workspace store."""

    project_name: str
    project_file: str
    primary_workspace_dir: str
    store: WorkspaceStore


def _resolve_project_context(project: str | None) -> _ProjectContext:
    """Resolve the project name and build a ``WorkspaceStore`` for it.

    Falls back to managed-checkout marker and sibling-scan inference when
    *project* is omitted.  Exits with a non-zero status when no project
    can be resolved or the project's primary workspace cannot be located.
    """
    project_name = project
    if not project_name:
        from sase.bead.project_name import infer_project_name_from_cwd

        project_name = infer_project_name_from_cwd()

    if not project_name:
        print(
            "Unable to infer project from current directory; pass -p/--project.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    project_file = get_project_file_path(project_name)
    primary = parse_workspace_dir(project_file) or ""
    if not primary:
        try:
            sibling_ctx = _materialize_sibling_project_context(
                project_name,
                project_file,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        if sibling_ctx is not None:
            return sibling_ctx
        print(
            f"Project '{project_name}' has no WORKSPACE_DIR in {project_file}.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    store = WorkspaceStore(primary, config=load_merged_config())
    return _ProjectContext(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        store=store,
    )


def _materialize_sibling_project_context(
    project_name: str,
    project_file: str,
) -> _ProjectContext | None:
    """Create missing ProjectSpec metadata for a configured sibling repo."""
    if not is_valid_sase_project_name(project_name):
        return None

    current = _current_project_context()
    if current is None or current.project_name == project_name:
        return None

    from sase.sibling_repos import resolve_sibling_repos_for_project

    resolution = resolve_sibling_repos_for_project(
        project_file=current.project_file,
        workspace_dir=current.primary_workspace_dir,
        workspace_num=0,
        materialize=False,
    )
    for warning in resolution.warnings:
        if f"{project_name!r}" in warning:
            raise RuntimeError(warning)

    sibling = next(
        (repo for repo in resolution.repos if repo.name == project_name),
        None,
    )
    if sibling is None:
        return None

    primary = sibling.primary_dir.rstrip("/") or sibling.primary_dir
    if not Path(primary).is_dir():
        raise RuntimeError(
            f"Configured sibling repo '{project_name}' primary path does not exist: "
            f"{primary}"
        )
    if _is_git_repo(current.primary_workspace_dir) and not _is_git_repo(primary):
        raise RuntimeError(
            f"Configured sibling repo '{project_name}' is not a Git checkout: {primary}"
        )

    metadata = _sibling_project_metadata(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        current_project_file=current.project_file,
    )
    _ensure_sibling_project_spec(project_file, metadata)

    store = WorkspaceStore(primary, config=load_merged_config())
    return _ProjectContext(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        store=store,
    )


def _current_project_context() -> _ProjectContext | None:
    from sase.bead.project_name import infer_project_name_from_cwd

    current_project = infer_project_name_from_cwd()
    if not current_project or not is_valid_sase_project_name(current_project):
        return None

    project_file = get_project_file_path(current_project)
    primary = parse_workspace_dir(project_file) or ""
    if not primary:
        return None

    return _ProjectContext(
        project_name=current_project,
        project_file=project_file,
        primary_workspace_dir=primary,
        store=WorkspaceStore(primary, config=load_merged_config()),
    )


def _sibling_project_metadata(
    *,
    project_name: str,
    project_file: str,
    primary_workspace_dir: str,
    current_project_file: str,
) -> dict[str, str]:
    metadata = {
        "WORKSPACE_DIR": primary_workspace_dir,
    }

    existing_bare_repo_dir = parse_bare_repo_dir(project_file)
    if existing_bare_repo_dir:
        metadata["BARE_REPO_DIR"] = existing_bare_repo_dir
        return metadata

    current_bare_repo_dir = parse_bare_repo_dir(current_project_file)
    if not current_bare_repo_dir:
        return metadata

    origin = _git_origin_url(primary_workspace_dir)
    if origin and _is_local_git_url(origin):
        metadata["BARE_REPO_DIR"] = str(Path(origin).expanduser())

    return metadata


def _ensure_sibling_project_spec(project_file: str, metadata: dict[str, str]) -> None:
    path = Path(project_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with changespec_lock(str(path)):
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""

        lifecycle = read_project_lifecycle_from_content(content)
        if lifecycle.explicit and lifecycle.state != "sibling":
            raise RuntimeError(
                f"ProjectSpec {path} has explicit PROJECT_STATE {lifecycle.state!r}; "
                "refusing to overwrite it with sibling"
            )

        updated = content
        if lifecycle.state != "sibling" or not lifecycle.explicit:
            updated = apply_project_lifecycle_update(updated, "sibling")
        for key, value in metadata.items():
            updated = _ensure_header_metadata(updated, key, value)

        write_changespec_atomic(
            str(path),
            updated,
            "Materialize sibling ProjectSpec metadata",
        )


def _ensure_header_metadata(content: str, key: str, value: str) -> str:
    prefix = f"{key}:"
    lines = content.splitlines(keepends=True)
    newline = _preferred_newline(lines, content)
    replacement = f"{prefix} {value}"
    header_end = _first_header_end(lines)

    for index, line in enumerate(lines[:header_end]):
        if not line.startswith(prefix):
            continue
        current = line.split(":", 1)[1].strip()
        if current:
            return content
        lines[index] = replacement + _line_ending(line, newline)
        return "".join(lines)

    insert_idx = _metadata_insert_index(lines)
    if insert_idx == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] = lines[-1] + newline
    lines.insert(insert_idx, replacement + newline)
    return "".join(lines)


def _first_header_end(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.startswith("NAME:"):
            return index
    return len(lines)


def _metadata_insert_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.startswith(("RUNNING:", "NAME:")):
            return index
    return len(lines)


def _preferred_newline(lines: list[str], content: str) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\r\n" if "\r\n" in content else "\n"


def _line_ending(line: str, default: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return default


def _is_git_repo(path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_origin_url(path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _is_local_git_url(url: str) -> bool:
    return not url.startswith(("http://", "https://", "git@", "ssh://"))


def _entry_row(num: int, entry: WorkspaceEntry) -> dict[str, Any]:
    return {
        "workspace_num": num,
        "checkout_dir": entry.checkout_dir.rstrip("/") or entry.checkout_dir,
        "materialization": entry.materialization,
        "role": entry.role,
        "pinned": entry.pinned,
        "created_at": entry.created_at,
        "last_used_at": entry.last_used_at,
        "generation": entry.generation,
        "exists": os.path.isdir(entry.checkout_dir.rstrip("/") or entry.checkout_dir),
    }


def _sorted_entries(registry: WorkspaceRegistry) -> list[tuple[int, WorkspaceEntry]]:
    items: list[tuple[int, WorkspaceEntry]] = []
    for key, entry in registry.workspaces.items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        items.append((num, entry))
    items.sort(key=lambda pair: pair[0])
    return items


def _claimed_nums(project_file: str) -> set[int]:
    return {claim.workspace_num for claim in get_claimed_workspaces(project_file)}


def _print_list_human(
    ctx: _ProjectContext,
    rows: list[dict[str, Any]],
) -> None:
    header = (
        f"Project: {ctx.project_name}  "
        f"key={ctx.store.project_key}  policy={ctx.store.root_policy}"
    )
    print(header)
    print(f"Root: {ctx.store.root_dir}")
    print()
    print(f"{'#':>4}  {'ROLE':<7} {'EXISTS':<6} {'PINNED':<6} {'PATH'}")
    for row in rows:
        print(
            f"{row['workspace_num']:>4}  "
            f"{row['role']:<7} "
            f"{('yes' if row['exists'] else 'no'):<6} "
            f"{('yes' if row['pinned'] else 'no'):<6} "
            f"{row['checkout_dir']}"
        )


def _handle_list(args: argparse.Namespace) -> int:
    ctx = _resolve_project_context(args.project)
    registry = load_or_init_registry(ctx.store)
    rows = [_entry_row(num, entry) for num, entry in _sorted_entries(registry)]

    if args.json:
        payload = {
            "project": ctx.project_name,
            "project_key": ctx.store.project_key,
            "root_policy": ctx.store.root_policy,
            "root_dir": ctx.store.root_dir,
            "primary_workspace_dir": ctx.store.primary_workspace_dir,
            "workspaces": rows,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_list_human(ctx, rows)
    return 0


def _resolve_checkout_path(
    ctx: _ProjectContext,
    workspace_num: int,
    *,
    materialize: bool,
) -> str:
    """Return the checkout path for *workspace_num*.

    Materializes (cloning when missing) only when *materialize* is true.
    """
    if materialize:
        path = ensure_workspace_checkout(
            ctx.primary_workspace_dir,
            workspace_num,
            config=load_merged_config(),
        )
        return path.rstrip("/") or path
    return ctx.store.resolve(workspace_num).checkout_dir.rstrip("/")


def _handle_path(args: argparse.Namespace) -> int:
    ctx = _resolve_project_context(args.project)
    workspace_num = int(args.workspace_num)
    if workspace_num < 0:
        print(
            f"workspace number must be >= 0, got {workspace_num}",
            file=sys.stderr,
        )
        return 2

    try:
        path = _resolve_checkout_path(ctx, workspace_num, materialize=False)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(path)
    return 0


def _handle_open(args: argparse.Namespace) -> int:
    return _handle_open_clean(args)


def _handle_open_clean(args: argparse.Namespace) -> int:
    ctx = _resolve_project_context(args.project)
    workspace_num = int(args.workspace_num)
    if workspace_num < 0:
        print(
            f"workspace number must be >= 0, got {workspace_num}",
            file=sys.stderr,
        )
        return 2

    try:
        from sase.sdd.files import ensure_bare_git_sdd_initialized

        ensure_bare_git_sdd_initialized(
            ctx.primary_workspace_dir,
            commit=True,
            push=True,
            raise_on_error=True,
        )
        path = _resolve_checkout_path(ctx, workspace_num, materialize=True)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    from sase.axe.runner_utils import prepare_workspace
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    clean_label = f"{ctx.project_name}-workspace-{workspace_num}"
    if not prepare_workspace(
        path,
        clean_label,
        VCS_DEFAULT_REVISION,
        backup_suffix="workspace-open",
        project_basename=ctx.project_name,
    ):
        return 1

    print(path)
    return 0


def _is_stale(
    entry: WorkspaceEntry,
    *,
    ttl_seconds: float,
    now: float,
) -> bool:
    if entry.pinned:
        return False
    return (now - entry.last_used_at) > ttl_seconds


def _remove_checkout(checkout_dir: str) -> None:
    path = checkout_dir.rstrip("/")
    if not path:
        return
    if os.path.islink(path):
        try:
            os.unlink(path)
        except OSError:
            pass
        return
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _remove_transition_symlink(ctx: _ProjectContext, workspace_num: int) -> str | None:
    """Remove any ``<primary>_<num>`` symlink left behind by migrations.

    Returns the symlink path that was removed, or ``None`` when there is
    nothing to do.
    """
    if workspace_num <= 1:
        return None
    if ctx.store.root_policy == "adjacent":
        return None
    base = ctx.primary_workspace_dir.rstrip("/")
    candidate = f"{base}_{workspace_num}"
    if os.path.islink(candidate):
        try:
            os.unlink(candidate)
        except OSError:
            return None
        return candidate
    return None


def _handle_cleanup(args: argparse.Namespace) -> int:
    ctx = _resolve_project_context(args.project)
    if not args.stale:
        print(
            "sase workspace cleanup currently requires -s/--stale.",
            file=sys.stderr,
        )
        return 2

    registry = load_or_init_registry(ctx.store)
    ttl_days = ctx.store.cleanup_ttl_days
    ttl_seconds = float(ttl_days) * 86400.0
    now = time.time()
    claimed = _claimed_nums(ctx.project_file)

    planned: list[tuple[int, WorkspaceEntry]] = []
    for num, entry in _sorted_entries(registry):
        if num == PRIMARY_WORKSPACE_NUM:
            continue
        if num in claimed:
            continue
        if not args.include_shares and entry.role == "share":
            continue
        if not _is_stale(entry, ttl_seconds=ttl_seconds, now=now):
            continue
        planned.append((num, entry))

    if not planned:
        print("No stale managed checkouts to remove.")
        return 0

    for num, entry in planned:
        verb = "would remove" if args.dry_run else "removing"
        print(f"{verb} #{num}: {entry.checkout_dir}")

    if args.dry_run:
        return 0

    for num, entry in planned:
        _remove_checkout(entry.checkout_dir)
        symlink = _remove_transition_symlink(ctx, num)
        if symlink:
            print(f"  removed transition symlink: {symlink}")
        registry.workspaces.pop(str(num), None)

    save_registry(ctx.store, registry)
    return 0


def _handle_repair(args: argparse.Namespace) -> int:
    ctx = _resolve_project_context(args.project)
    registry = load_or_init_registry(ctx.store)
    claimed = _claimed_nums(ctx.project_file)

    dropped: list[int] = []
    rematerialized: list[int] = []

    for num, entry in _sorted_entries(registry):
        if num == PRIMARY_WORKSPACE_NUM:
            continue
        checkout_dir = entry.checkout_dir.rstrip("/")
        if os.path.isdir(checkout_dir):
            continue
        if num in claimed:
            rematerialized.append(num)
            continue
        dropped.append(num)

    if not dropped and not rematerialized:
        print("Registry is in sync with the filesystem.")
        return 0

    for num in dropped:
        verb = "would drop" if args.dry_run else "dropping"
        print(f"{verb} stale registry entry for #{num}")
    for num in rematerialized:
        verb = "would re-materialize" if args.dry_run else "re-materializing"
        print(f"{verb} checkout for live claim #{num}")

    if args.dry_run:
        return 0

    for num in dropped:
        registry.workspaces.pop(str(num), None)
    save_registry(ctx.store, registry)

    for num in rematerialized:
        try:
            ensure_workspace_checkout(
                ctx.primary_workspace_dir,
                num,
                config=load_merged_config(),
            )
        except RuntimeError as exc:
            print(f"  failed to re-materialize #{num}: {exc}", file=sys.stderr)

    return 0


def _build_store_with_policy(
    primary_workspace_dir: str,
    *,
    policy: str,
) -> WorkspaceStore:
    """Return a ``WorkspaceStore`` rooted at *primary* with a forced policy.

    Migration constructs an explicit target store so users can stage the
    move before flipping ``workspace.root`` in their config.  The merged
    config is consulted for ancillary keys (e.g. ``project_key``,
    ``cleanup_ttl_days``) but ``root`` is overridden.
    """
    merged = load_merged_config() or {}
    section = dict(merged.get("workspace", {}) or {})
    section["root"] = policy
    return WorkspaceStore(primary_workspace_dir, config={"workspace": section})


def _discover_adjacent_workspaces(primary_workspace_dir: str) -> list[tuple[int, str]]:
    """Return ``(workspace_num, adjacent_path)`` pairs for sibling clones.

    Looks for ``<primary>_<num>/`` directories where ``<num>`` is a
    positive integer and the entry is a real directory (not a symlink).
    Results are sorted by workspace number for deterministic output.
    """
    base = primary_workspace_dir.rstrip("/")
    parent = os.path.dirname(base)
    if not parent or not os.path.isdir(parent):
        return []
    basename = os.path.basename(base)
    prefix = f"{basename}_"

    found: list[tuple[int, str]] = []
    for entry in os.listdir(parent):
        if not entry.startswith(prefix):
            continue
        suffix = entry[len(prefix) :]
        if not suffix.isdigit():
            continue
        num = int(suffix)
        if num <= 0:
            continue
        candidate = os.path.join(parent, entry)
        # Migration only moves real directories.  Symlinks (likely
        # transition symlinks from an earlier run) are skipped here so
        # finalize/cleanup can manage them separately.
        if os.path.islink(candidate) or not os.path.isdir(candidate):
            continue
        found.append((num, candidate))

    found.sort(key=lambda pair: pair[0])
    return found


def _transition_symlink_path(primary_workspace_dir: str, workspace_num: int) -> str:
    base = primary_workspace_dir.rstrip("/")
    return f"{base}_{workspace_num}"


def _handle_migrate(args: argparse.Namespace) -> int:
    if args.finalize:
        return _handle_migrate_finalize(args)

    if not args.to:
        print(
            "sase workspace migrate requires either --to <policy> or --finalize.",
            file=sys.stderr,
        )
        return 2

    ctx = _resolve_project_context(args.project)
    target_store = _build_store_with_policy(ctx.primary_workspace_dir, policy=args.to)
    if target_store.root_policy == "adjacent":
        print(
            "Refusing to migrate to the 'adjacent' policy "
            "(no managed root would be created).",
            file=sys.stderr,
        )
        return 2

    adjacent = _discover_adjacent_workspaces(ctx.primary_workspace_dir)
    if not adjacent:
        print("No adjacent managed checkouts found to migrate.")
        return 0

    planned: list[tuple[int, str, str]] = []
    refusals: list[str] = []
    for num, source in adjacent:
        target = target_store.resolve(num).checkout_dir.rstrip("/")
        if os.path.exists(target) and not os.path.samefile(source, target):
            refusals.append(
                f"#{num}: refusing to overwrite existing directory at {target}"
            )
            continue
        planned.append((num, source, target))

    for line in refusals:
        print(line, file=sys.stderr)

    for num, source, target in planned:
        verb = "would migrate" if args.dry_run else "migrating"
        print(f"{verb} #{num}: {source} -> {target}")
        if args.symlink_transition:
            symlink_path = _transition_symlink_path(ctx.primary_workspace_dir, num)
            sym_verb = "would symlink" if args.dry_run else "symlinking"
            print(f"  {sym_verb} {symlink_path} -> {target}")

    if args.dry_run:
        return 1 if refusals else 0

    registry = load_or_init_registry(target_store)
    now = time.time()
    for num, source, target in planned:
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        # ``os.replace`` is atomic on the same filesystem and overwrites
        # an empty target dir.  We already refused non-samefile existing
        # targets above, so any survivor must be the source itself.
        if not os.path.exists(target) or not os.path.samefile(source, target):
            shutil.move(source, target)
        wp = target_store.resolve(num)
        registry.workspaces[str(num)] = WorkspaceEntry(
            checkout_dir=wp.checkout_dir,
            materialization=wp.materialization,
            role="claim",
            created_at=now,
            last_used_at=now,
            pinned=False,
            generation=wp.generation,
        )
        if args.symlink_transition:
            symlink_path = _transition_symlink_path(ctx.primary_workspace_dir, num)
            if os.path.lexists(symlink_path):
                if os.path.islink(symlink_path):
                    try:
                        os.unlink(symlink_path)
                    except OSError as exc:
                        print(
                            f"  failed to replace existing symlink {symlink_path}: {exc}",
                            file=sys.stderr,
                        )
                        continue
                else:
                    print(
                        f"  refusing to overwrite real directory at {symlink_path}",
                        file=sys.stderr,
                    )
                    continue
            try:
                os.symlink(target, symlink_path)
            except OSError as exc:
                print(
                    f"  failed to create transition symlink {symlink_path}: {exc}",
                    file=sys.stderr,
                )

    save_registry(target_store, registry)
    return 1 if refusals else 0


def _handle_migrate_finalize(args: argparse.Namespace) -> int:
    ctx = _resolve_project_context(args.project)
    target_store = _build_store_with_policy(
        ctx.primary_workspace_dir, policy="xdg-state"
    )
    registry = load_or_init_registry(target_store)

    nums: set[int] = set()
    for key in registry.workspaces:
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        if num == PRIMARY_WORKSPACE_NUM:
            continue
        nums.add(num)

    # Even if the registry is empty, scan adjacent paths for stray
    # symlinks left by aborted migrations.
    base = ctx.primary_workspace_dir.rstrip("/")
    parent = os.path.dirname(base)
    if parent and os.path.isdir(parent):
        basename = os.path.basename(base)
        prefix = f"{basename}_"
        for entry in os.listdir(parent):
            if not entry.startswith(prefix):
                continue
            suffix = entry[len(prefix) :]
            if not suffix.isdigit():
                continue
            num = int(suffix)
            if num <= 0:
                continue
            candidate = os.path.join(parent, entry)
            if os.path.islink(candidate):
                nums.add(num)

    removed: list[str] = []
    for num in sorted(nums):
        symlink_path = _transition_symlink_path(ctx.primary_workspace_dir, num)
        if not os.path.islink(symlink_path):
            continue
        verb = "would remove" if args.dry_run else "removing"
        print(f"{verb} transition symlink #{num}: {symlink_path}")
        if not args.dry_run:
            try:
                os.unlink(symlink_path)
                removed.append(symlink_path)
            except OSError as exc:
                print(f"  failed to remove {symlink_path}: {exc}", file=sys.stderr)

    if not removed and not args.dry_run:
        print("No transition symlinks to remove.")
    return 0


_HANDLERS = {
    "list": _handle_list,
    "path": _handle_path,
    "open": _handle_open,
    "cleanup": _handle_cleanup,
    "repair": _handle_repair,
    "migrate": _handle_migrate,
}


def handle_workspace_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase workspace ...`` command to its handler."""
    sub = getattr(args, "workspace_subcommand", None)
    handler = _HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase workspace {list,path,open,cleanup,repair,migrate}",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(handler(args))

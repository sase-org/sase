"""Migration commands for ``sase workspace``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from typing import Protocol

from sase.workspace_provider.registry import (
    WorkspaceEntry,
    load_or_init_registry,
    save_registry,
)
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM, WorkspaceStore

from .workspace_handler_context import ConfigLoader
from .workspace_handler_list import ProjectResolver


class _StoreBuilder(Protocol):
    def __call__(
        self,
        primary_workspace_dir: str,
        *,
        policy: str,
    ) -> WorkspaceStore: ...


def build_store_with_policy(
    primary_workspace_dir: str,
    *,
    policy: str,
    load_config: ConfigLoader,
) -> WorkspaceStore:
    """Return a ``WorkspaceStore`` rooted at *primary* with a forced policy.

    Migration constructs an explicit target store so users can stage the
    move before flipping ``workspace.root`` in their config.  The merged
    config is consulted for ancillary keys (e.g. ``project_key``,
    ``cleanup_ttl_days``) but ``root`` is overridden.
    """
    merged = load_config() or {}
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


def handle_migrate(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
    build_store: _StoreBuilder,
) -> int:
    if args.finalize:
        return handle_migrate_finalize(
            args,
            resolve_project_context=resolve_project_context,
            build_store=build_store,
        )

    if not args.to:
        print(
            "sase workspace migrate requires either --to <policy> or --finalize.",
            file=sys.stderr,
        )
        return 2

    ctx = resolve_project_context(args.project)
    target_store = build_store(ctx.primary_workspace_dir, policy=args.to)
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
                            f"  failed to replace existing symlink {symlink_path}: "
                            f"{exc}",
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


def handle_migrate_finalize(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
    build_store: _StoreBuilder,
) -> int:
    ctx = resolve_project_context(args.project)
    target_store = build_store(ctx.primary_workspace_dir, policy="xdg-state")
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

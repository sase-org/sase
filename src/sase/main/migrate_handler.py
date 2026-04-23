"""Handler for ``sase migrate`` subcommands."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sase.core.paths import (
    _SHARD_DIR_RE,
    mark_shard_migrated,
    parse_filename_timestamp,
    shard_is_migrated,
)


# Directories sharded by YYYYMM, with the kind of entry stored in each:
#   "file" — individual files live directly under the subdir.
#   "dir"  — each entry is a subdirectory (e.g. plan_approval/<uuid>/).
_SHARDED_LAYOUT: dict[str, str] = {
    "chats": "file",
    "workflows": "file",
    "checks": "file",
    "dismissed_bundles": "file",
    "plans": "file",
    "plan_approval": "dir",
    "hooks": "file",
    "diffs": "file",
    "mentors": "file",
}


def _shard_name_for(ts: datetime) -> str:
    return ts.strftime("%Y%m")


def _shard_for_path(path: Path) -> str:
    """Pick the shard (YYYYMM) for a file or directory by timestamp or mtime."""
    ts = parse_filename_timestamp(path.name)
    if ts is not None:
        return _shard_name_for(ts)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = datetime.now().timestamp()
    return _shard_name_for(datetime.fromtimestamp(mtime))


def _migrate_one(
    base: Path,
    *,
    kind: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Migrate entries in ``base`` into ``YYYYMM/`` shards.

    Returns ``(moved, skipped)``.
    """
    if not base.is_dir():
        return (0, 0)

    moved = 0
    skipped = 0
    for entry in list(base.iterdir()):
        name = entry.name
        # Skip shard dirs and any hidden bookkeeping files.
        if _SHARD_DIR_RE.match(name):
            continue
        if name.startswith("."):
            continue
        if kind == "file" and not entry.is_file():
            skipped += 1
            continue
        if kind == "dir" and not entry.is_dir():
            skipped += 1
            continue

        shard = _shard_for_path(entry)
        dest_dir = base / shard
        dest = dest_dir / name
        if dest.exists():
            # Already present in target shard — leave in place to avoid
            # clobbering.  Legacy fallback in readers still finds it.
            skipped += 1
            continue
        if dry_run:
            moved += 1
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            # ``Path.rename`` is atomic within a filesystem; fall back to
            # a copy+unlink on cross-device setups.
            entry.rename(dest)
        except OSError:
            try:
                if kind == "file":
                    shutil.copy2(entry, dest)
                    entry.unlink()
                else:
                    shutil.copytree(entry, dest)
                    shutil.rmtree(entry)
            except OSError:
                skipped += 1
                continue
        moved += 1
    return (moved, skipped)


def handle_migrate_command(args: argparse.Namespace) -> None:
    sub = getattr(args, "migrate_subcommand", None)
    if sub == "shard-dirs":
        _handle_shard_dirs(args)
        return
    print(
        "Usage: sase migrate shard-dirs [--dry-run] [--force]",
        file=sys.stderr,
    )
    sys.exit(1)


def _handle_shard_dirs(args: argparse.Namespace) -> None:
    dry_run: bool = bool(getattr(args, "dry_run", False))
    force: bool = bool(getattr(args, "force", False))
    only: list[str] | None = getattr(args, "only", None)

    targets = list(_SHARDED_LAYOUT.items())
    if only:
        requested = set(only)
        unknown = requested - set(_SHARDED_LAYOUT)
        if unknown:
            print(
                f"Unknown sharded directories: {sorted(unknown)}",
                file=sys.stderr,
            )
            sys.exit(2)
        targets = [(n, k) for n, k in targets if n in requested]

    grand_total_moved = 0
    grand_total_skipped = 0
    for subdir, kind in targets:
        base = Path(f"~/.sase/{subdir}").expanduser()
        if not base.is_dir():
            print(f"{subdir}: (no directory, skipping)")
            continue
        if not force and shard_is_migrated(subdir):
            print(f"{subdir}: already migrated (.sharded sentinel present)")
            continue

        moved, skipped = _migrate_one(base, kind=kind, dry_run=dry_run)
        grand_total_moved += moved
        grand_total_skipped += skipped
        action = "would move" if dry_run else "moved"
        print(f"{subdir}: {action} {moved}, skipped {skipped}")

        if not dry_run:
            mark_shard_migrated(subdir)

    action = "Would move" if dry_run else "Moved"
    print(
        f"\n{action} {grand_total_moved} entries "
        f"({grand_total_skipped} skipped) across {len(targets)} directories."
    )

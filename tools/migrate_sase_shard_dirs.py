#!/usr/bin/env python3
"""Standalone ``~/.sase/`` YYYYMM shard migration script.

Re-implements ``sase migrate shard-dirs`` end-to-end as a single, stdlib-only
Python script that can be copied to any machine (``scp``, ``rsync``, pasted
over SSH, etc.) and run without requiring an up-to-date ``sase`` install.

Mirrors the logic in ``src/sase/main/migrate_handler.py`` and
``src/sase/core/paths.py`` as of commit ``852f8fd0``.  Keep this file in sync
with those two sources -- the parity test at
``tests/main/test_migrate_shard_dirs_script.py`` verifies they produce
byte-identical output on a synthetic tree.

Migrating another machine
-------------------------

    scp tools/migrate_sase_shard_dirs.py <host>:/tmp/
    ssh <host> 'python3 /tmp/migrate_sase_shard_dirs.py --dry-run'
    ssh <host> 'python3 /tmp/migrate_sase_shard_dirs.py'

Stop long-running ``sase`` processes on the target before running: concurrent
writes during migration aren't dangerous (unmovable entries are skipped and
remain reachable via the legacy-top-level reader fallback), but they add
noise to the "skipped" counts.

Requires Python >= 3.9.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


# Keep in sync with `src/sase/main/migrate_handler.py`.
_SHARDED_LAYOUT = {
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

_SHARD_DIR_RE = re.compile(r"^\d{6}$")
_TS_SUFFIX_RE = re.compile(r"-(\d{6}_\d{6})(?:\.\w+)?$")
_TS_PREFIX_RE = re.compile(r"^(\d{14})(?:__|\.|$)")
_SHARDED_SENTINEL = ".sharded"


def _parse_filename_timestamp(filename):
    # type: (str) -> datetime | None
    m = _TS_SUFFIX_RE.search(filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%y%m%d_%H%M%S")
        except ValueError:
            pass
    m = _TS_PREFIX_RE.match(filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return None


def _shard_name(ts):
    # type: (datetime) -> str
    return ts.strftime("%Y%m")


def _shard_for_path(path):
    # type: (Path) -> str
    ts = _parse_filename_timestamp(path.name)
    if ts is not None:
        return _shard_name(ts)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = datetime.now().timestamp()
    return _shard_name(datetime.fromtimestamp(mtime))


def _migrate_one(base, kind, dry_run):
    # type: (Path, str, bool) -> tuple[int, int]
    if not base.is_dir():
        return (0, 0)

    moved = 0
    skipped = 0
    for entry in list(base.iterdir()):
        name = entry.name
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
            skipped += 1
            continue
        if dry_run:
            moved += 1
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
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


def _shard_is_migrated(base):
    # type: (Path) -> bool
    return (base / _SHARDED_SENTINEL).exists()


def _mark_shard_migrated(base):
    # type: (Path) -> None
    base.mkdir(parents=True, exist_ok=True)
    (base / _SHARDED_SENTINEL).touch()


def _parse_args(argv):
    # type: (list[str] | None) -> argparse.Namespace
    parser = argparse.ArgumentParser(
        description=(
            "Migrate top-level files under ~/.sase/<subdir>/ into YYYYMM/ shards."
        ),
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Report what would move, change nothing.",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Re-run even if .sharded sentinel is present.",
    )
    parser.add_argument(
        "-o",
        "--only",
        metavar="DIRS",
        default=None,
        help=(
            "Comma-separated subdir names to migrate "
            "(default: all {}).".format(len(_SHARDED_LAYOUT))
        ),
    )
    parser.add_argument(
        "-s",
        "--sase-home",
        metavar="PATH",
        default=None,
        help="Override ~/.sase (default: $HOME/.sase).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    # type: (list[str] | None) -> int
    args = _parse_args(argv)

    if args.sase_home:
        sase_home = Path(args.sase_home).expanduser()
    else:
        sase_home = Path("~/.sase").expanduser()

    targets = list(_SHARDED_LAYOUT.items())
    if args.only:
        requested = {name.strip() for name in args.only.split(",") if name.strip()}
        unknown = requested - set(_SHARDED_LAYOUT)
        if unknown:
            print(
                "Unknown sharded directories: {}".format(sorted(unknown)),
                file=sys.stderr,
            )
            return 2
        targets = [(n, k) for n, k in targets if n in requested]

    grand_total_moved = 0
    grand_total_skipped = 0
    for subdir, kind in targets:
        base = sase_home / subdir
        if not base.is_dir():
            print("{}: (no directory, skipping)".format(subdir))
            continue
        if not args.force and _shard_is_migrated(base):
            print(
                "{}: already migrated (.sharded sentinel present)".format(subdir)
            )
            continue

        moved, skipped = _migrate_one(base, kind=kind, dry_run=args.dry_run)
        grand_total_moved += moved
        grand_total_skipped += skipped
        action = "would move" if args.dry_run else "moved"
        print("{}: {} {}, skipped {}".format(subdir, action, moved, skipped))

        if not args.dry_run:
            _mark_shard_migrated(base)

    action = "Would move" if args.dry_run else "Moved"
    print(
        "\n{} {} entries ({} skipped) across {} directories.".format(
            action, grand_total_moved, grand_total_skipped, len(targets)
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

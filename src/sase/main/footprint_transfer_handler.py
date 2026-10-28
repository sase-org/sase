"""Handlers for ``sase footprint export`` and ``sase footprint import``.

Split from ``footprint_handler`` to keep that module under its size
budget. Only this module imports the transfer helpers, keeping them off
the hot path.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date
from pathlib import Path


def handle_export(args: argparse.Namespace) -> int:
    """Export weekly identity-free packs to a file or stdout."""

    from sase.footprint.fold import fold_if_stale

    try:
        fold_if_stale()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not fold Footprint spool: {exc}", file=sys.stderr)
        return 1
    try:
        from sase.core.footprint_facade import footprint_export
        from sase.footprint.transfer import build_export_request, render_packs

        weeks = getattr(args, "weeks", None)
        if weeks is not None:
            weeks = int(weeks)
            if weeks < 1:
                raise ValueError(f"weeks must be at least 1, got {weeks}")
        request = build_export_request(weeks)
        packs = footprint_export(request)
        data = render_packs([dict(pack) for pack in packs])
        if not packs:
            print("No complete ISO weeks to export yet.")
            return 0
        if getattr(args, "preview", False):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            return 0
        output = getattr(args, "output", None)
        if output is None:
            raise ValueError("no output file given")
        _atomic_write_bytes(Path(output).expanduser(), data)
        labels = [str(pack.get("week", "")) for pack in packs]
        print(
            f"{len(packs)} packs · weeks {labels[0]}–{labels[-1]}"
            f" · {len(data)} bytes → {output}"
        )
        return 0
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"sase footprint export: {exc}", file=sys.stderr)
        return 1


def handle_import(args: argparse.Namespace) -> int:
    """Import weekly packs, replacing the previous imports."""

    try:
        from sase.core.footprint_facade import footprint_import
        from sase.footprint.paths import ledger_path
        from sase.footprint.transfer import read_pack_files

        files = getattr(args, "files", None) or []
        packs = read_pack_files(list(files))
        dry_run = bool(getattr(args, "dry_run", False))
        result = footprint_import(
            ledger_path(),
            packs,
            date.today().isoformat(),
            dry_run=dry_run,
        )
        count = int(result.get("packs_imported", 0) or 0)
        deduped = int(result.get("packs_deduped", 0) or 0)
        rows = int(result.get("feature_rows", 0) or 0)
        verb = "Would import" if dry_run else "Imported"
        print(f"{verb} {count} pack(s) ({deduped} deduped, {rows} feature rows)")
        print("Re-importing replaces the previous imports.")
        return 0
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"sase footprint import: {exc}", file=sys.stderr)
        return 1


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` atomically with mode 0600."""

    directory = target.parent if str(target.parent) else Path(".")
    fd, temporary = tempfile.mkstemp(prefix=".footprint-export-", dir=str(directory))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


__all__ = ["handle_export", "handle_import"]

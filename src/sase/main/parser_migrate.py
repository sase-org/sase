"""Argument parser definition for the ``sase migrate`` CLI subcommand.

TEMPORARY: deletion owner sase-x7.14. ``kit-backup`` (sase-x7.2.1.2) adds only
``backup`` and ``restore``; ``kit-driver`` (sase-x7.2.1.3) adds
``list``/``plan``/``resume``/``run``/``status``/``verify`` and wires the
group into ``_default_list_subcommands()``.
"""

from __future__ import annotations

import argparse

_GROUP_DESCRIPTION = (
    "Temporary offline migration kit for the canonical-only cutover. Backs "
    "up and restores declared roots outside every SASE runtime root; never "
    "runs automatically and is deleted in its entirety once the cutover "
    "completes.\n"
    "\n"
    "Every subcommand is a dry run unless -a/--apply is given."
)


def register_migrate_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase migrate`` subcommand parser."""
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Temporary offline migration kit: back up and restore a declared root",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_GROUP_DESCRIPTION,
        epilog=(
            "examples:\n"
            "  sase migrate backup ~/.sase\n"
            "  sase migrate backup ~/.sase --apply --secondary /mnt/backup\n"
            "  sase migrate restore athena-20260905T120000-a1b2c3\n"
            "  sase migrate restore athena-20260905T120000-a1b2c3 --apply"
        ),
    )
    migrate_sub = migrate_parser.add_subparsers(
        dest="migrate_subcommand",
        help="Migration kit subcommands",
        metavar="{backup,restore}",
    )

    backup_parser = migrate_sub.add_parser(
        "backup",
        help="Capture a verified, checksummed backup of one declared root",
        description=(
            "Capture a quiescent-as-possible, checksummed, SQLite-consistent "
            "backup of <root> outside every SASE runtime root. Dry run "
            "unless -a/--apply, in which case it writes MANIFEST.json, "
            "SHA256SUMS, and provenance.json alongside the copied payload."
        ),
    )
    backup_parser.add_argument(
        "root",
        metavar="<root>",
        help="Filesystem path to the directory root to back up",
    )
    backup_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply the backup (default: report what would be captured)",
    )
    backup_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    backup_parser.add_argument(
        "-s",
        "--secondary",
        metavar="<dir>",
        default=None,
        help="Also write a second durable copy of the backup under <dir>",
    )

    restore_parser = migrate_sub.add_parser(
        "restore",
        help="Verify and stage a restore of one backup; swap in with --apply",
        description=(
            "Verify a backup's SHA256SUMS before touching anything, restore "
            "it to a staging path, and report its diff and ownership deltas "
            "against the live root. Dry run unless -a/--apply, in which case "
            "the live root is moved aside (never deleted) and the staged "
            "copy is swapped into its place. The backup itself is never "
            "modified or deleted by a restore."
        ),
    )
    restore_parser.add_argument(
        "backup_id",
        metavar="<backup-id>",
        help="Backup id to restore, as printed by `sase migrate backup`",
    )
    restore_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply the restore (default: verify and stage only)",
    )
    restore_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    restore_parser.add_argument(
        "-r",
        "--root",
        metavar="<dir>",
        default=None,
        help="Live root to diff and swap into (default: the backed-up source root)",
    )


__all__ = ["register_migrate_parser"]

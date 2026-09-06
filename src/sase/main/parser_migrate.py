"""Argument parser definition for the ``sase migrate`` CLI subcommand.

TEMPORARY: deletion owner sase-x7.14. ``kit-backup`` (sase-x7.2.1.2) adds only
``backup`` and ``restore``; ``kit-driver`` (sase-x7.2.1.3) adds
``list``/``plan``/``resume``/``run``/``status``/``verify`` and wires the
group into ``_default_list_subcommands()``.
"""

from __future__ import annotations

import argparse

_GROUP_DESCRIPTION = (
    "Temporary offline migration kit for the canonical-only cutover. Lists, "
    "plans, backs up, restores, applies, resumes, statuses, and verifies "
    "declared cutover operations outside every SASE runtime root; never runs "
    "automatically and is deleted in its entirety once the cutover completes. "
    "Bare `sase migrate` delegates to `sase migrate list`.\n"
    "\n"
    "Every subcommand is a dry run unless -a/--apply is given."
)


def register_migrate_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase migrate`` subcommand parser."""
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Temporary offline migration kit for canonical-only cutover operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_GROUP_DESCRIPTION,
        epilog=(
            "examples:\n"
            "  sase migrate backup ~/.sase\n"
            "  sase migrate backup ~/.sase --apply --secondary /mnt/backup\n"
            "  sase migrate list\n"
            "  sase migrate plan state-residue --backup-id <backup-id>\n"
            "  sase migrate run <manifest> --apply\n"
            "  sase migrate restore athena-20260905T120000-a1b2c3\n"
            "  sase migrate restore athena-20260905T120000-a1b2c3 --apply\n"
            "  sase migrate resume <run-id> --apply\n"
            "  sase migrate status\n"
            "  sase migrate verify <run-id>"
        ),
    )
    migrate_sub = migrate_parser.add_subparsers(
        dest="migrate_subcommand",
        help="Migration kit subcommands",
        metavar="{backup,list,plan,restore,resume,run,status,verify}",
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

    list_parser = migrate_sub.add_parser(
        "list",
        help="List the fixed migration operation catalog",
        description=(
            "List the four shipped migration operations and report whether "
            "their declared roots are present for the selected SASE home. "
            "Bare `sase migrate` delegates here."
        ),
    )
    list_parser.add_argument(
        "-d",
        "--home",
        metavar="<dir>",
        default=None,
        help="Home directory used to resolve home-relative operation roots",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    list_parser.add_argument(
        "-r",
        "--root",
        metavar="<dir>",
        default=None,
        help="SASE home root used to resolve operation roots",
    )

    plan_parser = migrate_sub.add_parser(
        "plan",
        help="Dry-run one operation and persist its manifest",
        description=(
            "Plan <operation>, write runs/<run-id>/manifest.json plus an "
            "initial journal record, mutate no source data, and print the "
            "manifest path. Apply later with `sase migrate run <manifest>`."
        ),
    )
    plan_parser.add_argument(
        "operation",
        metavar="<operation>",
        help="Operation to plan: import-purge, lock-residue, procs-residue, or state-residue",
    )
    plan_parser.add_argument(
        "-b",
        "--backup-id",
        metavar="<id>",
        default=None,
        help="Verified backup id to bind into the manifest",
    )
    plan_parser.add_argument(
        "-d",
        "--home",
        metavar="<dir>",
        default=None,
        help="Home directory used to resolve home-relative operation roots",
    )
    plan_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    plan_parser.add_argument(
        "-r",
        "--root",
        metavar="<dir>",
        default=None,
        help="SASE home root used to resolve operation roots",
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

    resume_parser = migrate_sub.add_parser(
        "resume",
        help="Continue an interrupted migration run from its journal",
        description=(
            "Replay a run journal, re-check source digests when the run has "
            "not started applying, and continue from the next resumable step. "
            "Dry run unless -a/--apply."
        ),
    )
    resume_parser.add_argument(
        "run_id",
        metavar="<run-id>",
        help="Run id whose journal should be resumed",
    )
    resume_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply the resume (default: report the next step only)",
    )
    resume_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    resume_parser.add_argument(
        "-l",
        "--lock-timeout-ms",
        metavar="<ms>",
        type=int,
        default=5000,
        help="Bounded lock wait in milliseconds before refusing",
    )

    run_parser = migrate_sub.add_parser(
        "run",
        help="Execute a planned manifest",
        description=(
            "Run a manifest. Dry run checks digests, conflicts, and backup "
            "records without mutating data. -a/--apply executes the operation "
            "with a durable journal and receipt."
        ),
    )
    run_parser.add_argument(
        "manifest",
        metavar="<manifest>",
        help="Path printed by `sase migrate plan`",
    )
    run_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply the manifest (default: preflight only)",
    )
    run_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    run_parser.add_argument(
        "-l",
        "--lock-timeout-ms",
        metavar="<ms>",
        type=int,
        default=5000,
        help="Bounded lock wait in milliseconds before refusing",
    )

    status_parser = migrate_sub.add_parser(
        "status",
        help="Show migration runs, journal state, and resumability",
        description="Show every recorded migration run and its latest journal state.",
    )
    status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )

    verify_parser = migrate_sub.add_parser(
        "verify",
        help="Re-check post-conditions for one run",
        description=(
            "Load one run manifest and re-check the operation's "
            "post-conditions and semantic fingerprints."
        ),
    )
    verify_parser.add_argument(
        "run_id",
        metavar="<run-id>",
        help="Run id to verify",
    )
    verify_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )


__all__ = ["register_migrate_parser"]

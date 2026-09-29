"""Note and evidence argument parser definitions for bead subcommands."""

from __future__ import annotations

import argparse

from sase.main._parser_bead_lifecycle_shared import AT_PATH_READS_IT

__all__ = [
    "register_bead_attach_parser",
    "register_bead_attachment_parser",
    "register_bead_note_parser",
    "register_bead_plus_one_parser",
]


def register_bead_plus_one_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead +1``."""
    parser = subparsers.add_parser(
        "+1",
        help="Corroborate an existing task with independent evidence",
        description=(
            "Record one independently attributed report on an existing task bead. "
            "Each reporter counts at most once; later details belong in `sase bead "
            "note`. Draft tasks promote to ready; closed tasks promote only when "
            "the report's observation window starts after the current close."
        ),
        epilog=(
            "Examples:\n"
            '  sase bead +1 sase-ab -n "Reproduced on Linux with v0.14.0"\n'
            '  sase bead +1 ab -n "Trace confirms the same failure" '
            "-R research:202608/trace.txt\n"
            '  sase bead +1 sase-ab -a agent.two -n "Independent reproduction"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("id", help="Full or shorthand task bead ID")
    parser.add_argument(
        "-a",
        "--author",
        metavar="NAME",
        help="Reporter recorded on the evidence (default: current agent, else owner)",
    )
    parser.add_argument(
        "-n",
        "--note",
        required=True,
        metavar="TEXT",
        help=(
            f"Required independent reproduction or impact evidence; {AT_PATH_READS_IT}"
        ),
    )
    parser.add_argument(
        "-R",
        "--ref",
        action="append",
        help="Artifact reference supporting the evidence (repeatable)",
    )
    parser.add_argument(
        "-S",
        "--allow-sensitive",
        dest="allow_sensitive",
        action="store_true",
        help=(
            "Attach files from sensitive paths (with the "
            "bead_note_attachments beta flag on)"
        ),
    )
    parser.add_argument(
        "--verified-after-close",
        action="store_true",
        help=(
            "Assert this was reproduced on a tree that already contains the "
            "close, so the observation window is now instead of this "
            "runtime's start. Requires the bead to already be closed."
        ),
    )


def register_bead_attach_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead attach``."""
    parser = subparsers.add_parser(
        "attach",
        help="Attach file snapshots to a bead note",
        description=(
            "Attach snapshots of files to a bead as a new attributed note. "
            "The bead keeps the exact bytes on every machine, even after the "
            "file is gone. Requires the bead_note_attachments beta flag. "
            "Use - to read one attachment from stdin (with -N/--name)."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead attach sase-ab ./shot.png\n"
            '  sase bead attach sase-ab -n "Crash trace" ./trace.json\n'
            "  sase bead attach sase-ab -N trace.json - < /tmp/trace.json\n"
            "  sase bead attach sase-ab ./a.png ./b.png"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("id", help="Full or shorthand issue ID")
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="Files to attach; use - to read one attachment from stdin",
    )
    parser.add_argument(
        "-a",
        "--author",
        metavar="NAME",
        help="Author recorded on the entry (default: current agent, else store owner)",
    )
    parser.add_argument(
        "-n",
        "--note",
        metavar="TEXT",
        help=(
            "Optional prose stored above the attachment tokens; "
            "@<path> references inside it attach too"
        ),
    )
    parser.add_argument(
        "-N",
        "--name",
        metavar="NAME",
        help=(
            "Attachment name; valid only with one file, "
            "and required when the file is - (stdin)"
        ),
    )
    parser.add_argument(
        "-S",
        "--allow-sensitive",
        dest="allow_sensitive",
        action="store_true",
        help="Attach files from sensitive paths",
    )


def register_bead_attachment_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead attachment``."""
    parser = subparsers.add_parser(
        "attachment",
        help="List attachment snapshots or print a local view path",
        description=(
            "List content-addressed attachment snapshots on a bead, or print "
            "the absolute local view path for one attachment. "
            "Invoking 'sase bead attachment' without a subcommand delegates "
            "to 'sase bead attachment list'. Neither command fetches and "
            "neither checks the bead_note_attachments beta flag."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead attachment list sase-ab\n"
            "  sase bead attachment list sase-ab --json\n"
            "  sase bead attachment path sase-ab shot.png"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    attachment_subparsers = parser.add_subparsers(dest="attachment_action")
    list_parser = attachment_subparsers.add_parser(
        "list",
        help="List attachment snapshots",
        description=(
            "List attachment snapshots on one bead, or on every bead when no "
            "ID is given. Text output shows one descriptor per attachment "
            "plus the cached view path or an unavailable marker."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    list_parser.add_argument(
        "id",
        nargs="?",
        help="Full or shorthand issue ID",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        dest="json",
        action="store_true",
        help="Emit machine-readable attachment data",
    )
    path_parser = attachment_subparsers.add_parser(
        "path",
        help="Print the absolute local view path for one attachment",
        description=(
            "Materialize the extension-preserving local view and print its "
            "absolute path. Fails with a clear unavailable error when no "
            "local object exists; it never fetches."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    path_parser.add_argument("id", help="Full or shorthand issue ID")
    path_parser.add_argument("name", help="Attachment name")


def register_bead_note_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead note``."""
    parser = subparsers.add_parser(
        "note", help="Append, edit, or retract an attributed note entry"
    )
    parser.add_argument("id", help="Full or shorthand issue ID")
    parser.add_argument(
        "text",
        nargs="*",
        help=(
            "Note text to append. Inside note text, @<path> attaches a "
            "snapshot of that file (with the bead_note_attachments beta "
            "flag on; the bead keeps the exact bytes on every machine). "
            "Accepted forms: @./shot.png, @~/logs/crash.log, "
            '@/tmp/trace.json, @docs/plan.md, @"name with spaces.png", '
            "or a bare @name.ext for a known file type. Write @@ where you "
            "need a literal @ that would otherwise start a reference. "
            "me@host, @large, and @research:… citations never need "
            "escaping. A note argument that is only @<file> still reads "
            "the note's text from that file. To attach files without "
            "prose, use `sase bead attach`. Required to append or with "
            "--edit; omit with --remove"
        ),
    )
    parser.add_argument(
        "-a",
        "--author",
        metavar="NAME",
        help="Author recorded on the entry (default: current agent, else store owner)",
    )
    parser.add_argument(
        "-S",
        "--allow-sensitive",
        dest="allow_sensitive",
        action="store_true",
        help=(
            "Attach files from sensitive paths (with the "
            "bead_note_attachments beta flag on)"
        ),
    )
    edit_group = parser.add_mutually_exclusive_group()
    edit_group.add_argument(
        "-e",
        "--edit",
        type=int,
        metavar="N",
        help=(
            "Rewrite note #N (the ordinal shown by `sase bead read`); "
            "re-read `read` after any edit or removal, since ordinals shift"
        ),
    )
    edit_group.add_argument(
        "-x",
        "--remove",
        type=int,
        metavar="N",
        help=(
            "Retract note #N (the ordinal shown by `sase bead read`); "
            "`sase bead history` keeps the retracted record"
        ),
    )

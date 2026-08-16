"""Argument parser definition for the ``sase flag`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_flag_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase flag`` subcommand parser."""
    flag_parser = subparsers.add_parser(
        "flag",
        help="Inspect SASE feature flags and scaffold a new one",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect the code-owned SASE feature-flag registry and scaffold a "
            "new flag plus its dedicated removal bead.\n"
            "\n"
            "With no subcommand, `sase flag` defaults to `sase flag list`.\n"
            "\n"
            "`sase flag new` only runs in a SASE-managed checkout "
            "(is_sase_managed: true in sase/sase.yml). The registry lives in "
            "the SASE source tree; scaffolding a flag from another project "
            "has nowhere to paste the entry. `list` and `show` work in any "
            "project because they report this process's resolved flags."
        ),
        epilog=(
            "examples:\n"
            "  sase flag                         # same as `sase flag list`\n"
            "  sase flag list                    # every registered flag\n"
            "  sase flag show plugins_enabled    # one flag's provenance\n"
            "  sase flag new demo_key            # bead + paste-ready entry\n"
            "  sase flag new demo_key -k beta -s global -r 2026-12-01/0.19.0"
        ),
    )
    flag_sub = flag_parser.add_subparsers(
        dest="flag_subcommand",
        help="Flag subcommands",
        metavar="{list,new,show}",
    )

    list_parser = flag_sub.add_parser(
        "list",
        help="List every registered feature flag and its resolved value",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List every registered feature flag: the key chip, kind, default, "
            "effective value, source layer, scope, bead id and status, and the "
            "removal countdown. Inherited SASE_FEATURE_FLAGS values are marked "
            "ENV so a long-running detached process cannot hide an override."
        ),
        epilog=("examples:\n  sase flag list\n  sase flag list --json"),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    new_parser = flag_sub.add_parser(
        "new",
        help="Create a flag bead and print the registry entry to paste",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Scaffold a new feature flag. Creates the dedicated `flag` removal "
            "bead (unless -k/--kind is ops) with remove_by_date = today + 90 "
            "days and remove_by_release = the current minor plus two, then "
            "prints the registry entry to paste and a both-states test "
            "checklist.\n"
            "\n"
            "Requires is_sase_managed: true in this checkout's sase/sase.yml."
        ),
        epilog=(
            "examples:\n"
            "  sase flag new demo_key\n"
            "  sase flag new demo_key -d 'Opt-in beta' -k beta -s global\n"
            "  sase flag new demo_key -r 2026-12-01/0.19.0 -z small"
        ),
    )
    new_parser.add_argument(
        "flag_key",
        metavar="<key>",
        help="Snake_case registry key for the new flag",
    )
    new_parser.add_argument(
        "-d",
        "--description",
        default=None,
        help="Flag description (ops flags use this as the required rationale)",
    )
    new_parser.add_argument(
        "-k",
        "--kind",
        choices=("beta", "ops", "sunset", "wip"),
        default=None,
        help="Flag kind (default: beta)",
    )
    new_parser.add_argument(
        "-r",
        "--remove-by",
        metavar="DATE/RELEASE",
        default=None,
        help="Override both thresholds, e.g. 2026-12-01/0.19.0",
    )
    new_parser.add_argument(
        "-s",
        "--scope",
        choices=("global", "project"),
        default=None,
        help="Flag scope (default: global)",
    )
    new_parser.add_argument(
        "-z",
        "--size",
        choices=("xsmall", "small", "medium", "large", "xlarge"),
        default=None,
        help="Optional size for the created flag bead",
    )

    show_parser = flag_sub.add_parser(
        "show",
        help="Show one feature flag's provenance, bead, and call sites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show the full FeatureFlagDecision for one key: per-layer "
            "provenance, the dedicated flag bead and both removal thresholds, "
            "and the flag's call sites in the installed SASE package."
        ),
        epilog=(
            "examples:\n  sase flag show demo_key\n  sase flag show demo_key --json"
        ),
    )
    show_parser.add_argument(
        "flag_key",
        metavar="<key>",
        help="Registered feature-flag key to inspect",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )


__all__ = ["register_flag_parser"]

"""Argument parser definition for the ``sase flag`` CLI subcommand."""

from __future__ import annotations

import argparse

_FLAG_SUBCOMMANDS = "{disable,enable,list,new,show}"
_MUTATION_PRECEDENCE = (
    "Saved machine preferences outrank registry defaults, user config, and "
    "overlay config. Inherited SASE_FEATURE_FLAGS and root "
    "-f/--enable-feature or -F/--disable-feature still win for this process."
)
_MUTATION_RESTART = (
    "On success, AXE is restarted when it is already running so new processes "
    "see the saved value. A stopped AXE daemon is left stopped. Any separately "
    "running ACE session must be restarted in its own terminal. Repeating an "
    "already-saved enable or disable still retries that AXE restart. A restart "
    "failure does not roll back the saved preference."
)
_MUTATION_STATE = (
    "The choice is stored in the SASE-owned machine-state file "
    "`feature_flags.json` under SASE_HOME (normally ~/.sase/feature_flags.json). "
    "It is not written to ~/.config/sase/sase.yml, overlays, or project-local "
    "sase.yml."
)


def register_flag_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase flag`` subcommand parser."""
    flag_parser = subparsers.add_parser(
        "flag",
        help="Inspect, persist, and scaffold SASE feature flags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect the code-owned SASE feature-flag registry, persist a "
            "machine-local enable or disable choice, and scaffold a new flag "
            "plus its dedicated removal bead.\n"
            "\n"
            "With no subcommand, `sase flag` defaults to `sase flag list`.\n"
            "\n"
            "`sase flag new` only runs in a SASE-managed checkout "
            "(is_sase_managed: true in sase/sase.yml). The registry lives in "
            "the SASE source tree; scaffolding a flag from another project "
            "has nowhere to paste the entry. `list`, `show`, `enable`, and "
            "`disable` work in any project: they report this process's "
            "resolved flags or persist a machine-local preference.\n"
            "\n"
            f"{_MUTATION_STATE}\n"
            "\n"
            f"{_MUTATION_PRECEDENCE}"
        ),
        epilog=(
            "examples:\n"
            "  sase flag                         # same as `sase flag list`\n"
            "  sase flag list                    # every registered flag\n"
            "  sase flag enable ref_sync_gesture # persist on for this machine\n"
            "  sase flag disable ref_sync_gesture\n"
            "  sase flag show plugins_enabled    # one flag's provenance\n"
            "  sase flag new demo_key --when-enabled '...' --when-disabled '...' "
            "--remove-when '...'\n"
            "  sase flag new demo_key -k beta -r 2026-12-01/0.19.0 "
            "--when-enabled @on.txt --when-disabled @off.txt --remove-when @gate.txt"
        ),
    )
    flag_sub = flag_parser.add_subparsers(
        dest="flag_subcommand",
        help="Flag subcommands",
        metavar=_FLAG_SUBCOMMANDS,
    )

    _add_mutation_parser(
        flag_sub,
        "disable",
        help_text="Persistently disable a registered feature flag",
    )
    _add_mutation_parser(
        flag_sub,
        "enable",
        help_text="Persistently enable a registered feature flag",
    )

    list_parser = flag_sub.add_parser(
        "list",
        help="List every registered feature flag and its resolved value",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List every registered feature flag: the key chip, kind, default, "
            "effective value, source layer, bead id and status, and the "
            "removal countdown. Inherited SASE_FEATURE_FLAGS values are marked "
            "ENV so a long-running detached process cannot hide an override.\n"
            "\n"
            "A non-empty listing ends with a compact statistics footer: how "
            "many flags were rendered and which kinds they use, how many "
            "resolve on versus off, how many decisions came from a layer "
            "above the registry default, and whether any loaded removal bead "
            "is soon or due. Homogeneous kind or on/off values fold into the "
            "count head. For example:\n"
            "\n"
            "  3 flags · 2 beta  1 sunset · 2 on  1 off · 1 overridden · "
            "⧗ 1 soon  ⧗ 1 due\n"
            "\n"
            "`--json` keeps the versioned machine contract and does not "
            "include this footer."
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
            "task bead with remove_by_date = today + 90 days and "
            "remove_by_release = the current minor plus two, then prints the "
            "registry entry to paste and a both-states test checklist.\n"
            "\n"
            "--when-enabled, --when-disabled, and --remove-when are required "
            "and each accepts `@<path>` to read the value from a file.\n"
            "\n"
            "Requires is_sase_managed: true in this checkout's sase/sase.yml."
        ),
        epilog=(
            "examples:\n"
            "  sase flag new demo_key --when-enabled 'the new path runs' "
            "--when-disabled 'the old path runs' --remove-when 'soaked a week'\n"
            "  sase flag new demo_key -k beta -r 2026-12-01/0.19.0 "
            "--when-enabled @on.txt --when-disabled @off.txt --remove-when @gate.txt"
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
        help="Registry scaffold description (default: --when-enabled)",
    )
    new_parser.add_argument(
        "-k",
        "--kind",
        choices=("beta", "sunset"),
        default=None,
        help="Flag kind (default: beta)",
    )
    new_parser.add_argument(
        "--when-enabled",
        required=True,
        help="What the code does with this flag enabled; accepts @<path>",
    )
    new_parser.add_argument(
        "--when-disabled",
        required=True,
        help=(
            "What the code does with this flag disabled, i.e. the branch "
            "deleted at removal; accepts @<path>"
        ),
    )
    new_parser.add_argument(
        "--remove-when",
        required=True,
        help="What must be true before the disabled branch is deleted; accepts @<path>",
    )
    new_parser.add_argument(
        "-r",
        "--remove-by",
        metavar="DATE/RELEASE",
        default=None,
        help="Override both thresholds, e.g. 2026-12-01/0.19.0",
    )
    new_parser.add_argument(
        "-z",
        "--size",
        choices=("xsmall", "small", "medium", "large", "xlarge"),
        default="small",
        help="Size for the created flag bead (default: small)",
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


def _add_mutation_parser(
    flag_sub: argparse._SubParsersAction,
    name: str,
    *,
    help_text: str,
) -> None:
    parser = flag_sub.add_parser(
        name,
        help=help_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            f"Persistently {name} a registered feature flag on this machine.\n"
            "\n"
            f"{_MUTATION_STATE}\n"
            "\n"
            f"{_MUTATION_PRECEDENCE}\n"
            "\n"
            f"{_MUTATION_RESTART}"
        ),
        epilog=(
            "examples:\n"
            f"  sase flag {name} ref_sync_gesture\n"
            f"  sase flag {name} ref_sync_gesture --json"
        ),
    )
    parser.add_argument(
        "flag_key",
        metavar="<key>",
        help="Registered feature-flag key to persist",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )


__all__ = ["register_flag_parser"]

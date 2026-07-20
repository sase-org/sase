"""Argument parser definition for the ``sase agent-cli`` command group."""

from __future__ import annotations

import argparse


def _add_inventory_flags(parser: argparse.ArgumentParser) -> None:
    """Add the cache and output flags shared by agent-CLI commands."""
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a stable, machine-readable JSON envelope",
    )
    parser.add_argument(
        "-o",
        "--offline",
        action="store_true",
        help="Use cached latest versions only; never contact the npm registry",
    )
    parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass cached latest versions and query the npm registry",
    )


def register_agent_cli_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase agent-cli`` command group."""
    agent_cli_parser = subparsers.add_parser(
        "agent-cli",
        help="Inspect and safely update supported coding-agent CLIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect the coding-agent CLIs supported by SASE and update installs "
            "whose management method can be identified safely. SASE automates "
            "npm-managed installs and provider-declared self-update commands; "
            "ambiguous installs are left untouched with an exact manual command "
            "when available and a canonical documentation URL. SASE never uses "
            "sudo and never guesses an update command.\n"
            "\n"
            "With no subcommand, `sase agent-cli` defaults to "
            "`sase agent-cli list`."
        ),
        epilog=(
            "examples:\n"
            "  sase agent-cli                       # same as `sase agent-cli list`\n"
            "  sase agent-cli list                  # inspect all supported CLIs\n"
            "  sase agent-cli list -v               # include paths and docs URLs\n"
            "  sase agent-cli list -o -j            # cached inventory as JSON\n"
            "  sase agent-cli update codex          # update one CLI\n"
            "  sase agent-cli update claude codex   # update selected CLIs\n"
            "  sase agent-cli update -a             # update every safe candidate\n"
            "  sase agent-cli update -a -n          # preview commands and skips"
        ),
    )
    agent_cli_sub = agent_cli_parser.add_subparsers(
        dest="agent_cli_subcommand",
        help="Agent CLI subcommands",
        metavar="{list,update}",
    )

    list_parser = agent_cli_sub.add_parser(
        "list",
        help="List supported agent CLIs, versions, and install methods",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List every supported coding-agent CLI with its resolved binary, "
            "installed and latest versions, install method, and an `↑` marker "
            "when an update is available. Missing CLIs show their install hint. "
            "Use `-v|--verbose` to include resolved executable paths and canonical "
            "documentation URLs."
        ),
        epilog=(
            "examples:\n"
            "  sase agent-cli list\n"
            "  sase agent-cli list --json\n"
            "  sase agent-cli list --offline\n"
            "  sase agent-cli list --refresh\n"
            "  sase agent-cli list --verbose"
        ),
    )
    _add_inventory_flags(list_parser)
    list_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show resolved executable paths, canonical docs URLs, and probe errors",
    )

    update_parser = agent_cli_sub.add_parser(
        "update",
        help="Update selected agent CLIs (or every safe candidate with --all)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Update one or more supported coding-agent CLIs through the shared "
            "safe update planner. Pass `-a|--all` to select every installed CLI. "
            "Each command runs sequentially without a shell; unsupported, "
            "ambiguous, missing, bundled, and already-current CLIs are reported "
            "as explicit skips.\n"
            "\n"
            "Use `-n|--dry-run` to print every exact command and skip reason "
            "without changing anything. A bare invocation without names or "
            "`-a|--all` is a usage error."
        ),
        epilog=(
            "examples:\n"
            "  sase agent-cli update codex\n"
            "  sase agent-cli update claude opencode\n"
            "  sase agent-cli update -a\n"
            "  sase agent-cli update -a --dry-run\n"
            "  sase agent-cli update codex --json\n"
            "  sase agent-cli update codex --offline"
        ),
    )
    update_parser.add_argument(
        "names",
        nargs="*",
        metavar="<name>",
        help="CLI names to update (provider, binary, or display name); omit with --all",
    )
    update_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Select every supported installed agent CLI",
    )
    update_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a stable, machine-readable JSON envelope",
    )
    update_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show exact commands and skip reasons without running anything",
    )
    update_parser.add_argument(
        "-o",
        "--offline",
        action="store_true",
        help="Use cached latest versions only; never contact the npm registry",
    )
    update_parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass cached latest versions and query the npm registry",
    )


__all__ = ["register_agent_cli_parser"]

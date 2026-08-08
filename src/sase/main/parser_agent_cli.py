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
            "Inspect the coding-agent CLIs supported by SASE and install or "
            "update installs whose management method can be identified safely. "
            "SASE automates npm-managed installs, provider-declared self-update "
            "commands, and provider-declared install scripts; ambiguous installs "
            "are left untouched with an exact manual command when available and "
            "a canonical documentation URL. SASE never uses sudo, never uses a "
            "shell, never guesses an update command, and never edits your shell "
            "startup files.\n"
            "\n"
            "With no subcommand, `sase agent-cli` defaults to "
            "`sase agent-cli list`."
        ),
        epilog=(
            "examples:\n"
            "  sase agent-cli                       # same as `sase agent-cli list`\n"
            "  sase agent-cli install muse -n       # preview URL, digest, target\n"
            "  sase agent-cli install muse -y       # fetch and run the installer\n"
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
        metavar="{install,list,update}",
    )

    install_parser = agent_cli_sub.add_parser(
        "install",
        help="Install agent CLIs that declare an install script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Install one or more supported coding-agent CLIs from the install "
            "script their provider declares. SASE downloads the script itself, "
            "shows the URL, its SHA-256 digest, the exact command, and the "
            "target directory, and only then runs it without a shell. CLIs that "
            "declare no install script are reported as explicit skips with the "
            "manual command to run instead.\n"
            "\n"
            "Running a remote script always needs confirmation: pass `-y|--yes` "
            "or answer the interactive prompt. Use `-n|--dry-run` to see the "
            "plan, digest included, without executing anything.\n"
            "\n"
            "After a successful install SASE reports where the binary landed "
            "and whether that directory is on PATH, printing the exact export "
            "line to add when it is not. SASE never edits your shell startup "
            "files."
        ),
        epilog=(
            "examples:\n"
            "  sase agent-cli install muse --dry-run\n"
            "  sase agent-cli install muse --yes\n"
            "  sase agent-cli install muse --force --yes\n"
            "  sase agent-cli install muse --dry-run --json"
        ),
    )
    install_parser.add_argument(
        "names",
        nargs="*",
        metavar="<name>",
        help="CLI names to install (provider, binary, or display name)",
    )
    install_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Reinstall even when the CLI is already installed",
    )
    install_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a stable, machine-readable JSON envelope",
    )
    install_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show the URL, digest, command, and target without running anything",
    )
    install_parser.add_argument(
        "-o",
        "--offline",
        action="store_true",
        help="Use cached latest versions only; never contact the npm registry",
    )
    install_parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass cached latest versions and query the npm registry",
    )
    install_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Run the install script without an interactive confirmation",
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

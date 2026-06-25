"""Argument parser definition for the ``sase plugin`` CLI subcommand."""

from __future__ import annotations

import argparse


def _add_load_flags(parser: argparse.ArgumentParser) -> None:
    """Add the cache/refresh and JSON flags shared by plugin subcommands."""
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass the cache and refetch the catalog from GitHub",
    )


def register_plugin_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase plugin`` subcommand parser."""
    plugin_parser = subparsers.add_parser(
        "plugin",
        help="Discover SASE plugins from the GitHub catalog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Discover every SASE plugin that exists by treating the GitHub "
            "`sase-plugin` topic as the canonical registry. The catalog "
            "distinguishes built-in plugins (published under the official "
            "`sase-org` org) from community plugins, and marks which are "
            "installed in the current environment. It is fetched from GitHub "
            "once and cached, so commands are instant on repeat runs; pass "
            "`-r|--refresh` to bypass the cache and refetch.\n"
            "\n"
            "With no subcommand, `sase plugin` defaults to `sase plugin list`."
        ),
        epilog=(
            "examples:\n"
            "  sase plugin                 # same as `sase plugin list`\n"
            "  sase plugin list            # catalog of all known plugins\n"
            "  sase plugin list -v         # add stars, last-updated, topics\n"
            "  sase plugin list -r         # refetch the catalog from GitHub\n"
            "  sase plugin show github     # detail view of one plugin\n"
            "  sase plugin show github -j  # machine-readable JSON"
        ),
    )
    plugin_sub = plugin_parser.add_subparsers(
        dest="plugin_subcommand",
        help="Plugin subcommands",
        metavar="{list,show}",
    )

    list_parser = plugin_sub.add_parser(
        "list",
        help="List all known SASE plugins (built-in and community)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List every known SASE plugin in two clearly-labeled sections — "
            "built-in (official `sase-org`) first, then community (third-party) "
            "— marking which are installed and at what version. The footer "
            "shows cache age and the exact refresh command."
        ),
        epilog=(
            "examples:\n"
            "  sase plugin list\n"
            "  sase plugin list --verbose\n"
            "  sase plugin list --refresh\n"
            "  sase plugin list --json"
        ),
    )
    _add_load_flags(list_parser)
    list_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show extra columns: stars, last updated, and the full topic list",
    )

    show_parser = plugin_sub.add_parser(
        "show",
        help="Show detailed information about a single SASE plugin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show a detailed view of one SASE plugin: description, installed "
            "status and entry points, repository, homepage, topics, stars, "
            "last update, and license. Community plugins lead with a prominent "
            "third-party warning. <plugin_name> matches the short name "
            "(`github`), the repo (`sase-github`), or the full name "
            "(`sase-org/sase-github`); an unknown name prints `did you mean…?` "
            "suggestions and exits non-zero."
        ),
        epilog=(
            "examples:\n"
            "  sase plugin show github\n"
            "  sase plugin show sase-github\n"
            "  sase plugin show github --refresh\n"
            "  sase plugin show github --json"
        ),
    )
    show_parser.add_argument(
        "plugin_name",
        metavar="<plugin_name>",
        help="Plugin name to show (short name, repo, or owner/repo full name)",
    )
    _add_load_flags(show_parser)

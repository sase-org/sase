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
            "  sase plugin                    # same as `sase plugin list`\n"
            "  sase plugin list               # catalog of all known plugins\n"
            "  sase plugin list -v            # add stars, last-updated, topics\n"
            "  sase plugin list -r            # refetch the catalog from GitHub\n"
            "  sase plugin show github        # detail view of one plugin\n"
            "  sase plugin show github -j     # machine-readable JSON\n"
            "  sase plugin install github     # install a plugin into sase's env\n"
            "  sase plugin update github      # upgrade one installed plugin\n"
            "  sase plugin update -a          # upgrade every installed plugin"
        ),
    )
    plugin_sub = plugin_parser.add_subparsers(
        dest="plugin_subcommand",
        help="Plugin subcommands",
        metavar="{install,list,show,update}",
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

    install_parser = plugin_sub.add_parser(
        "install",
        help="Install a plugin into the same environment as sase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Install a SASE plugin into the *same* uv tool environment as sase, "
            "so its entry points are discovered the next time sase runs. The "
            "<plugin> name is resolved through the GitHub catalog (`github` -> "
            "`sase-github`); a raw requirement, git URL, or local path is passed "
            "through verbatim. By default the plugin is installed from its "
            "published distribution; pass `-g|--git` to install from its "
            "repository instead.\n"
            "\n"
            "This only works when sase was installed via `uv tool install sase` "
            "(the canonical install path). When run from a pip/pipx install or a "
            "dev checkout's virtualenv, it fails fast with an actionable message "
            "instead of touching your environment. uv's `--with` set is "
            "reconstructed from sase's uv receipt, so existing plugins and "
            "editable/dev installs are preserved.\n"
            "\n"
            "Use `-n|--dry-run` to preview the exact uv command and resulting "
            "plugin set without changing anything."
        ),
        epilog=(
            "examples:\n"
            "  sase plugin install github         # resolve via the catalog\n"
            "  sase plugin install sase-github    # repo name also works\n"
            "  sase plugin install github -g      # install from its git repo\n"
            "  sase plugin install github -n      # preview without installing\n"
            "  sase plugin install 'sase-foo==1.2'  # raw requirement passthrough"
        ),
    )
    install_parser.add_argument(
        "plugin",
        metavar="<plugin>",
        help="Plugin to install (catalog name, repo, requirement, or git URL)",
    )
    install_parser.add_argument(
        "-g",
        "--git",
        action="store_true",
        help="Install from the plugin's git repository instead of an index",
    )
    install_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    install_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show the planned uv command and plugin set without running it",
    )
    install_parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass the cache and refetch the catalog from GitHub",
    )

    update_parser = plugin_sub.add_parser(
        "update",
        help="Upgrade one installed plugin (or every plugin with --all)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Upgrade a single installed SASE plugin to its latest version while "
            "leaving sase core and every other plugin pinned. Pass `-a|--all` to "
            "upgrade every installed plugin in one shot (still leaving sase core "
            "pinned). To upgrade sase core together with all plugins, use "
            "`sase update` instead.\n"
            "\n"
            "Like `sase plugin install`, this only works when sase was installed "
            "via `uv tool install sase`, reconstructs uv's `--with` set from "
            "sase's receipt (preserving editable/dev installs), and fails fast "
            "with an actionable message otherwise. A plugin that is not installed "
            "yields a hint to run `sase plugin install <plugin>` instead.\n"
            "\n"
            "Use `-n|--dry-run` to preview the exact uv command without changing "
            "anything."
        ),
        epilog=(
            "examples:\n"
            "  sase plugin update github      # upgrade one installed plugin\n"
            "  sase plugin update -a          # upgrade every installed plugin\n"
            "  sase plugin update github -n   # preview without upgrading\n"
            "  sase plugin update github -j   # stable machine-readable JSON"
        ),
    )
    update_parser.add_argument(
        "plugin",
        metavar="<plugin>",
        nargs="?",
        help="Plugin to upgrade (catalog name or repo); omit with -a|--all",
    )
    update_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Upgrade every installed plugin (sase core stays pinned)",
    )
    update_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    update_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show the planned uv command without running it",
    )
    update_parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass the cache and refetch the catalog from GitHub",
    )

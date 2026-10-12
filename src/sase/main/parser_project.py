"""Argument parser definition for the ``sase project`` CLI subcommand."""

from __future__ import annotations

import argparse
from typing import Any

from sase.core.project_lifecycle_wire import PROJECT_LIFECYCLE_STATES

_STATE_METAVAR = "{" + ",".join(PROJECT_LIFECYCLE_STATES) + "}"


class _ExclusiveProjectSetupFlag(argparse.Action):
    """Store one setup boolean while rejecting the other setup choice."""

    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        *,
        conflicts_with: str,
        **kwargs: Any,
    ) -> None:
        self.conflicts_with = conflicts_with
        super().__init__(option_strings, dest, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del values, option_string
        if bool(getattr(namespace, self.conflicts_with, False)):
            parser.error("--setup and --no-setup are mutually exclusive")
        setattr(namespace, self.dest, True)


def _parse_create_option(value: str) -> str:
    """Accept one ``KEY=VALUE`` create option, rejecting empty keys."""

    if "=" not in value or not value.partition("=")[0].strip():
        raise argparse.ArgumentTypeError(
            f"create option must be KEY=VALUE, got {value!r}"
        )
    return value


def _add_force(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow disabling a project that still has live work",
    )


def register_project_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase project`` subcommand parser."""
    from sase.ops.cli import add_operation_io_flags

    project_parser = subparsers.add_parser(
        "project",
        help="Inspect and mutate project lifecycle state",
        description=(
            "Inspect project lifecycle state and the current project. "
            "Running `sase project` defaults to `sase project list`."
        ),
    )
    project_sub = project_parser.add_subparsers(
        dest="project_subcommand",
        help="Project subcommands",
        metavar="{add,alias,create,current,disable,enable,list,set-current,set-state,show,suggest}",
    )

    add_parser = project_sub.add_parser(
        "add",
        help="Register an existing repository as a SASE project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Register an existing repository as an enabled SASE project. "
            "New projects are enabled by default. Use --check to preview "
            "without writes. Setup can write the "
            "repository's sase/sase.yml, commit it, and push the default "
            "branch; agents may preview freely, while explicit setup is "
            "human-only. Interrupted operations can be resumed by repeating "
            "the same command. Successful setup may hand off to `sase init`."
        ),
        epilog=(
            "examples:\n"
            "  sase project add gh:sase-org/sase --check\n"
            "  sase project add gh:sase-org/sase --yes\n"
            "  sase project add owner/repo --setup --yes\n"
            "  sase project add git:my-repo --name tools --alias local-tools"
        ),
    )
    add_parser.add_argument("ref", metavar="REF", help="Existing repository reference")
    add_parser.add_argument(
        "-a",
        "--alias",
        action="append",
        default=[],
        metavar="ALIAS",
        help="Add a project alias (repeatable)",
    )
    add_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Show the read-only plan without applying it",
    )
    add_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a plan document or NDJSON apply events",
    )
    add_parser.add_argument(
        "-m",
        "--make-current",
        action="store_true",
        help="Make the registered project current",
    )
    add_parser.add_argument(
        "-n",
        "--name",
        metavar="NAME",
        help="Set the project display name",
    )
    add_parser.add_argument(
        "-S",
        "--no-setup",
        action=_ExclusiveProjectSetupFlag,
        conflicts_with="setup",
        default=False,
        nargs=0,
        help="Register without the remote management commit and push",
    )
    add_operation_io_flags(add_parser)
    add_parser.add_argument(
        "-s",
        "--setup",
        action=_ExclusiveProjectSetupFlag,
        conflicts_with="no_setup",
        default=False,
        nargs=0,
        help="Request SASE management setup (human-only commit and push)",
    )
    add_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply without a confirmation prompt",
    )

    create_parser = project_sub.add_parser(
        "create",
        help="Create a repository and register it as a SASE project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create a remote or bare repository and register it as an "
            "enabled SASE project. REF is gh:OWNER/NAME, OWNER/NAME, or "
            "git:NAME. Provider options are validated before any create "
            "subprocess. --check is read-only and available to agents; "
            "apply is human-only unless it runs as an approved "
            "/sase_gate option or SASE_PROJECT_CREATE_BYPASS holds a "
            "reason. Interrupted operations resume by repeating the same "
            "command. Successful setup may hand off to `sase init`."
        ),
        epilog=(
            "examples:\n"
            "  sase project create gh:sase-org/forge --check\n"
            "  sase project create sase-org/forge -v private --yes\n"
            "  sase project create git:tools --name tools --yes"
        ),
    )
    create_parser.add_argument(
        "ref",
        metavar="REF",
        help="Repository to create (gh:OWNER/NAME, OWNER/NAME, or git:NAME)",
    )
    create_parser.add_argument(
        "-a",
        "--alias",
        action="append",
        default=[],
        metavar="ALIAS",
        help="Add a project alias (repeatable)",
    )
    create_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Show the read-only plan without applying it",
    )
    create_parser.add_argument(
        "-d",
        "--description",
        metavar="TEXT",
        help="Repository description (sugar for --option description=TEXT)",
    )
    create_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a plan document or NDJSON apply events",
    )
    create_parser.add_argument(
        "-m",
        "--make-current",
        action="store_true",
        help="Make the registered project current",
    )
    create_parser.add_argument(
        "-n",
        "--name",
        metavar="NAME",
        help="Set the project display name",
    )
    create_parser.add_argument(
        "-S",
        "--no-setup",
        action=_ExclusiveProjectSetupFlag,
        conflicts_with="setup",
        default=False,
        nargs=0,
        help="Register without the remote management commit and push",
    )
    create_parser.add_argument(
        "-O",
        "--option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        type=_parse_create_option,
        help="Provider creation option (repeatable; validated strictly)",
    )
    add_operation_io_flags(create_parser)
    create_parser.add_argument(
        "-s",
        "--setup",
        action=_ExclusiveProjectSetupFlag,
        conflicts_with="no_setup",
        default=False,
        nargs=0,
        help="Request SASE management setup (human-only commit and push)",
    )
    create_parser.add_argument(
        "-v",
        "--visibility",
        metavar="VISIBILITY",
        help="Repository visibility (sugar for --option visibility=VISIBILITY)",
    )
    create_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply without a confirmation prompt",
    )

    alias_parser = project_sub.add_parser(
        "alias",
        help="Inspect and mutate project aliases",
    )
    alias_sub = alias_parser.add_subparsers(
        dest="alias_subcommand",
        help="Project alias subcommands",
        metavar="{add,clear,list,remove}",
    )
    alias_add_parser = alias_sub.add_parser(
        "add",
        help="Add an alias to a project",
    )
    alias_add_parser.add_argument("project", help="Project name")
    alias_add_parser.add_argument("alias", help="Alias name")
    alias_clear_parser = alias_sub.add_parser(
        "clear",
        help="Remove all aliases from a project",
    )
    alias_clear_parser.add_argument("project", help="Project name")
    alias_list_parser = alias_sub.add_parser(
        "list",
        help="List project aliases",
    )
    alias_list_parser.add_argument(
        "project",
        nargs="?",
        help="Optional project name to inspect",
    )
    alias_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    alias_parser.set_defaults(alias_subcommand="list", project=None, json=False)
    alias_remove_parser = alias_sub.add_parser(
        "remove",
        help="Remove an alias from a project",
    )
    alias_remove_parser.add_argument("project", help="Project name")
    alias_remove_parser.add_argument("alias", help="Alias name")

    current_parser = project_sub.add_parser(
        "current",
        help="Show the current project derived from the VCS macro MRU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print the current project: the first VCS macro MRU entry that "
            "resolves to an enabled SASE project.\n\n"
            "The current project is a pure read of the VCS macro MRU store "
            "(~/.sase/vcs_macro_mru.json). Launch an agent on a project, or "
            "on a Patch owned by that project, to make it current. "
            "`sase project set-current` performs the same MRU promotion "
            "without a launch, and the Projects tab in sase's TUI binds "
            "that operation.\n\n"
            "Human output colors the project name with that project's accent "
            "and reports the canonical directory key, the origin (project or "
            "patch, naming the Patch when applicable), and the MRU ref that "
            "produced it. When nothing resolves, the command explains how to "
            "set a current project and exits 0."
        ),
        epilog=("examples:\n  sase project current\n  sase project current --json"),
    )
    current_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    for command, help_text in (
        ("disable", "Disable a project"),
        ("enable", "Enable a project"),
        ("activate", argparse.SUPPRESS),
        ("archive", argparse.SUPPRESS),
        ("close", argparse.SUPPRESS),
        ("deactivate", argparse.SUPPRESS),
    ):
        lifecycle_parser = project_sub.add_parser(
            command,
            help=help_text,
        )
        lifecycle_parser.add_argument("project", help="Project name")
        _add_force(lifecycle_parser)

    list_parser = project_sub.add_parser(
        "list",
        help="List SASE projects by lifecycle state",
    )
    list_parser.add_argument(
        "-s",
        "--state",
        default="enabled",
        metavar="{enabled,disabled,sibling,all}",
        help="Lifecycle state to include (default: enabled)",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    set_current_parser = project_sub.add_parser(
        "set-current",
        help="Set the current project by promoting it in the VCS macro MRU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Make PROJECT the current project by promoting it to the head of "
            "the VCS macro MRU store (~/.sase/vcs_macro_mru.json).\n\n"
            "This is the same write a launch on that project performs. The "
            "project must be enabled and launchable. The Projects tab in "
            "sase's TUI binds the same operation.\n\n"
            "Human output prints a one-line result, then the same project "
            "detail as `sase project current`. --json emits status, message, "
            "and the project payload (or null). Exits 0 when the project is "
            "current (set or already current) and 1 when it is not."
        ),
        epilog=(
            "examples:\n"
            "  sase project set-current sase\n"
            "  sase project set-current sase --json"
        ),
    )
    set_current_parser.add_argument(
        "project",
        help="Project name, alias, or directory key",
    )
    set_current_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    set_state_parser = project_sub.add_parser(
        "set-state",
        help="Set a project's lifecycle state",
    )
    set_state_parser.add_argument("project", help="Project name")
    set_state_parser.add_argument(
        "state",
        metavar=_STATE_METAVAR,
        help="Target lifecycle state",
    )
    _add_force(set_state_parser)

    show_parser = project_sub.add_parser(
        "show",
        help="Show one project's lifecycle record",
    )
    show_parser.add_argument("project", help="Project name")
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    suggest_parser = project_sub.add_parser(
        "suggest",
        help="Rank repositories worth adding as projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Rank repositories worth adding as SASE projects, grouped as "
            "RESUME, ON THIS MACHINE, SUGGESTED, LINKED TO YOUR PROJECTS, "
            "and DISABLED PROJECTS. Discovery is cache-first per owner and "
            "read-only: nothing is cloned, created, or registered.\n\n"
            "Human output prints one grouped section per workspace provider "
            "with a health line, owner errors with their remedy, a hidden "
            "row footer, and a closing `sase project add REF` hint. "
            "--json emits the machine-readable candidate document."
        ),
        epilog=(
            "examples:\n"
            "  sase project suggest\n"
            "  sase project suggest gh --owner sase-org --refresh\n"
            "  sase project suggest --all --json"
        ),
    )
    suggest_parser.add_argument(
        "provider",
        nargs="?",
        help="Workspace provider workflow type (default: every provider)",
    )
    suggest_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include hidden rows (sidecars, forks, archived, projects)",
    )
    suggest_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    suggest_parser.add_argument(
        "-o",
        "--owner",
        action="append",
        default=None,
        metavar="OWNER",
        help="Restrict discovery to the named owner (repeatable)",
    )
    suggest_parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help="Bypass the cached repository lists",
    )

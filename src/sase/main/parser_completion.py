"""Argument parser definition for the ``sase completion`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.completion.candidates.protocol import DEFAULT_LIMIT


def register_completion_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase completion`` command group."""
    completion_parser = subparsers.add_parser(
        "completion",
        help="Generate and inspect shell completion for the sase CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Generate native shell-completion scripts from the live sase "
            "argparse tree, install them where the shell will actually "
            "load them, and inspect the structural spec those scripts "
            "are built from.\n"
            "\n"
            "With no subcommand, `sase completion` defaults to "
            "`sase completion list`.\n"
            "\n"
            "Write generated scripts to a file. Do not "
            '`eval "$(sase completion zsh)"` — that would pay a full sase '
            "startup on every new shell."
        ),
        epilog=(
            "examples:\n"
            "  sase completion                         # same as list\n"
            "  sase completion bash                    # print a bash script\n"
            "  sase completion bash -o "
            "~/.local/share/bash-completion/completions/sase\n"
            "  sase completion fish                    # print fish complete directives\n"
            "  sase completion fish -o ~/.config/fish/completions/sase.fish\n"
            "  sase completion install                 # detect the shell and install\n"
            "  sase completion install zsh             # write, zcompile, verify, stamp\n"
            "  sase completion list                    # shells, path, zwc, stamp\n"
            "  sase completion spec                    # structural JSON\n"
            "  sase completion spec -j -o spec.json    # write the snapshot artifact\n"
            "  sase completion zsh                     # print a compsys script\n"
            "  sase completion zsh -o ~/.zfunc/_sase   # write `_sase` for fpath\n"
            "  sase completion candidates bead         # live bead-id candidates"
        ),
    )
    completion_sub = completion_parser.add_subparsers(
        dest="completion_subcommand",
        help="Completion subcommands",
        metavar="{bash,candidates,fish,install,list,spec,zsh}",
    )

    _register_bash_parser(completion_sub)
    _register_candidates_parser(completion_sub)
    _register_fish_parser(completion_sub)
    _register_install_parser(completion_sub)
    _register_list_parser(completion_sub)
    _register_spec_parser(completion_sub)
    _register_zsh_parser(completion_sub)


def _register_candidates_parser(subparsers: argparse._SubParsersAction) -> None:
    candidates_parser = subparsers.add_parser(
        "candidates",
        help="Print live completion candidates for one value kind",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print `value<TAB>description` candidate lines for one value "
            "kind, optionally filtered by a prefix. A pre-argparse fast "
            "path in entry.py handles this command ahead of argparse for "
            "every normal invocation; reaching this parser means the fast "
            "path deferred, which happens only for `--help` and argv shapes "
            "it does not recognize."
        ),
        epilog=(
            "examples:\n"
            "  sase completion candidates project\n"
            "  sase completion candidates bead sase-oc\n"
            "  sase completion candidates bead sase-oc -l 20"
        ),
    )
    candidates_parser.add_argument(
        "kind",
        metavar="KIND",
        help="Value kind to list candidates for (e.g. project, bead)",
    )
    candidates_parser.add_argument(
        "prefix",
        metavar="PREFIX",
        nargs="?",
        default="",
        help="Only print candidates whose value starts with PREFIX",
    )
    candidates_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        metavar="N",
        help="Print at most N candidates (default: 200)",
    )
    candidates_parser.add_argument(
        "-p",
        "--project",
        metavar="NAME",
        default=None,
        help="Scope candidates to project NAME",
    )


def _register_list_parser(subparsers: argparse._SubParsersAction) -> None:
    list_parser = subparsers.add_parser(
        "list",
        help="Show which shells have a generator and their install status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List every supported shell, whether sase can generate a "
            "completion script for it, the installed path, `.zwc` "
            "freshness, stamp version, and the resolved install status."
        ),
        epilog=("examples:\n  sase completion list\n  sase completion list --json"),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )


def _register_install_parser(subparsers: argparse._SubParsersAction) -> None:
    install_parser = subparsers.add_parser(
        "install",
        help="Write, zcompile, verify, and stamp a completion script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Install native shell completion for sase. Detects the shell "
            "from $SHELL and the parent process when SHELL is omitted, "
            "picks a directory the shell actually scans, writes the "
            "script atomically, zcompiles it (zsh), verifies "
            "`_comps[sase]` registration, and stamps the install.\n"
            "\n"
            "Never edits ~/.zshrc. If registration fails, the exact "
            "`fpath=(...)` line to add before compinit is printed.\n"
            "\n"
            'Do not `eval "$(sase completion zsh)"`.'
        ),
        epilog=(
            "examples:\n"
            "  sase completion install\n"
            "  sase completion install zsh\n"
            "  sase completion install zsh -t ~/.zfunc\n"
            "  sase completion install bash -d\n"
            "  sase completion install fish -f"
        ),
    )
    install_parser.add_argument(
        "shell",
        nargs="?",
        choices=("bash", "fish", "zsh"),
        default=None,
        help="Shell to install for (default: detect from $SHELL and the parent process)",
    )
    install_parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Print the install plan without touching the filesystem",
    )
    install_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite a completion file sase did not write",
    )
    install_parser.add_argument(
        "-t",
        "--target",
        metavar="DIR",
        default=None,
        help="Directory to write the script into",
    )


def _register_spec_parser(subparsers: argparse._SubParsersAction) -> None:
    spec_parser = subparsers.add_parser(
        "spec",
        help="Print the structural completion spec as JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print the structural completion spec — the same JSON artifact "
            "the checked-in snapshot gate compares against. Descriptions "
            "are replaced by per-command digests so wording churn is a "
            "one-line diff. Use this as a stable integration point for "
            "other tools."
        ),
        epilog=(
            "examples:\n"
            "  sase completion spec\n"
            "  sase completion spec --json\n"
            "  sase completion spec -o cli_spec.json"
        ),
    )
    spec_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    spec_parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Write the spec to FILE instead of stdout",
    )


def _register_bash_parser(subparsers: argparse._SubParsersAction) -> None:
    _register_script_parser(
        subparsers,
        "bash",
        help_text="Emit a bash completion script",
        description=(
            "Print a bash completion script registered with "
            "`complete -o default -F _sase sase`. Source it from "
            "bash-completion's completions directory, or write it with "
            "-o/--output. Kinded value slots call `__sase_candidates` "
            "(filled in later). Do not eval the output on every shell start."
        ),
        epilog=(
            "examples:\n"
            "  sase completion bash\n"
            "  sase completion bash -o "
            "~/.local/share/bash-completion/completions/sase"
        ),
    )


def _register_fish_parser(subparsers: argparse._SubParsersAction) -> None:
    _register_script_parser(
        subparsers,
        "fish",
        help_text="Emit a fish completion script",
        description=(
            "Print fish `complete -c sase` directives conditioned on a "
            "`__sase_cmd` helper that resolves the current command path. "
            "Descriptions are passed with `-d`. Write the file to "
            "`~/.config/fish/completions/sase.fish` with -o/--output. "
            "Do not eval the output on every shell start."
        ),
        epilog=(
            "examples:\n"
            "  sase completion fish\n"
            "  sase completion fish -o ~/.config/fish/completions/sase.fish"
        ),
    )


def _register_zsh_parser(subparsers: argparse._SubParsersAction) -> None:
    _register_script_parser(
        subparsers,
        "zsh",
        help_text="Emit a native zsh compsys completion script",
        description=(
            "Print a `#compdef sase` compsys script with `_arguments -C "
            "-s -S`, option descriptions, exclusion lists, mutex groups, "
            "and remainder handling. Place the file on `fpath` as `_sase` "
            "before `compinit` and `zcompile` it. Do not eval the output."
        ),
        epilog=(
            "examples:\n  sase completion zsh\n  sase completion zsh -o ~/.zfunc/_sase"
        ),
    )


def _register_script_parser(
    subparsers: argparse._SubParsersAction,
    name: str,
    *,
    help_text: str,
    description: str,
    epilog: str,
) -> None:
    parser = subparsers.add_parser(
        name,
        help=help_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=description,
        epilog=epilog,
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Write the script to FILE instead of stdout",
    )


__all__ = ["register_completion_parser"]

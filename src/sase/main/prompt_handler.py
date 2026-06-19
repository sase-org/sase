"""Handler for ``sase prompt`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_prompt_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate prompt sub-handler."""
    sub = getattr(args, "prompt_subcommand", None)

    if sub == "copy":
        from sase.prompt.cli_copy import handle_prompt_copy

        handle_prompt_copy(args)
        sys.exit(0)

    if sub == "delete":
        from sase.prompt.cli_maintenance import handle_prompt_delete

        handle_prompt_delete(args)
        sys.exit(0)

    if sub == "doctor":
        from sase.prompt.cli_maintenance import handle_prompt_doctor

        handle_prompt_doctor(args)
        sys.exit(0)

    if sub == "edit":
        from sase.prompt.cli_run import handle_prompt_edit

        handle_prompt_edit(args)
        sys.exit(0)

    if sub == "export":
        from sase.prompt.cli_export import handle_prompt_export

        handle_prompt_export(args)
        sys.exit(0)

    if sub == "list":
        from sase.prompt.cli_list import handle_prompt_list

        handle_prompt_list(args)
        sys.exit(0)

    if sub == "prune":
        from sase.prompt.cli_maintenance import handle_prompt_prune

        handle_prompt_prune(args)
        sys.exit(0)

    if sub == "run":
        from sase.prompt.cli_run import handle_prompt_run

        handle_prompt_run(args)
        sys.exit(0)

    if sub == "save":
        from sase.prompt.cli_export import handle_prompt_save

        handle_prompt_save(args)
        sys.exit(0)

    if sub == "search":
        from sase.prompt.cli_search import handle_prompt_search

        handle_prompt_search(args)
        sys.exit(0)

    if sub == "select":
        from sase.prompt.cli_run import handle_prompt_select

        handle_prompt_select(args)
        sys.exit(0)

    if sub == "show":
        from sase.prompt.cli_show import handle_prompt_show

        handle_prompt_show(args)
        sys.exit(0)

    if sub == "stats":
        from sase.prompt.cli_stats import handle_prompt_stats

        handle_prompt_stats(args)
        sys.exit(0)

    print(
        "Usage: sase prompt"
        " {copy,delete,doctor,edit,export,list,prune,run,save,search,select,show,stats}"
    )
    sys.exit(1)

"""Handler for ``sase glossary`` subcommands."""

from __future__ import annotations

import argparse
import sys

from sase.glossary.compat import (
    find_glossary_web,
    glossary_project_directory,
    memory_all_namespace,
    memory_log_namespace,
    memory_read_namespace,
    memory_show_namespace,
    memory_web_show_namespace,
    print_glossary_deprecation_notice,
)


def handle_glossary_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase glossary`` sub-handler."""
    sub = getattr(args, "glossary_subcommand", None) or "list"

    if sub == "add":
        _dispatch_add(args)
        sys.exit(0)

    if sub == "all":
        print_glossary_deprecation_notice("all", "sase memory show glossary")
        _dispatch_all(args)
        sys.exit(0)

    if sub == "del":
        _dispatch_del(args)
        sys.exit(0)

    if sub == "list":
        print_glossary_deprecation_notice("list", "sase memory web show glossary")
        _dispatch_list(args)
        sys.exit(0)

    if sub == "log":
        print_glossary_deprecation_notice("log", "sase memory log --include glossary")
        _dispatch_log(args)
        sys.exit(0)

    if sub == "read":
        print_glossary_deprecation_notice("read", "sase memory read glossary:<term>")
        _dispatch_read(args)
        sys.exit(0)

    if sub == "show":
        print_glossary_deprecation_notice("show", "sase memory show glossary:<term>")
        _dispatch_show(args)
        sys.exit(0)

    print("Usage: sase glossary {add,all,del,list,log,read,show}", file=sys.stderr)
    sys.exit(1)


def _dispatch_add(args: argparse.Namespace) -> None:
    web = find_glossary_web(getattr(args, "project", None))
    if web is not None:
        from sase.glossary.web_mutation import handle_glossary_add_web_command

        handle_glossary_add_web_command(args, web)
        return
    from sase.glossary.cli_add import handle_glossary_add_command

    handle_glossary_add_command(args)


def _dispatch_del(args: argparse.Namespace) -> None:
    web = find_glossary_web(getattr(args, "project", None))
    if web is not None:
        from sase.glossary.web_mutation import handle_glossary_del_web_command

        handle_glossary_del_web_command(args, web)
        return
    from sase.glossary.cli_del import handle_glossary_del_command

    handle_glossary_del_command(args)


def _dispatch_read(args: argparse.Namespace) -> None:
    if find_glossary_web(getattr(args, "project", None)) is not None:
        from sase.memory.cli_read import handle_memory_read_command

        handle_memory_read_command(memory_read_namespace(args))
        return
    from sase.glossary.cli_read import handle_glossary_read_command

    handle_glossary_read_command(args)


def _dispatch_show(args: argparse.Namespace) -> None:
    if find_glossary_web(getattr(args, "project", None)) is not None:
        from sase.memory.cli_show import handle_memory_show_command

        handle_memory_show_command(memory_show_namespace(args))
        return
    from sase.glossary.cli_show import handle_glossary_show_command

    handle_glossary_show_command(args)


def _dispatch_all(args: argparse.Namespace) -> None:
    if find_glossary_web(getattr(args, "project", None)) is not None:
        from sase.memory.cli_show import handle_memory_show_command

        handle_memory_show_command(memory_all_namespace(args))
        return
    from sase.glossary.cli_all import handle_glossary_all_command

    handle_glossary_all_command(args)


def _dispatch_list(args: argparse.Namespace) -> None:
    if find_glossary_web(getattr(args, "project", None)) is not None:
        from sase.memory.web.cli import handle_memory_web_show_command

        handle_memory_web_show_command(memory_web_show_namespace(args))
        return
    from sase.glossary.cli_list import handle_glossary_list_command

    handle_glossary_list_command(args)


def _dispatch_log(args: argparse.Namespace) -> None:
    project_ref = getattr(args, "project", None)
    if find_glossary_web(project_ref) is not None:
        from sase.memory.cli_log import handle_memory_log_command

        with glossary_project_directory(project_ref):
            handle_memory_log_command(memory_log_namespace(args))
        return
    from sase.glossary.cli_log import handle_glossary_log_command

    handle_glossary_log_command(args)


__all__ = ["handle_glossary_command"]

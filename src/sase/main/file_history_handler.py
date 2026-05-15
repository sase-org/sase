"""Handler for the 'sase file-history' command."""

import argparse
import json
import sys


def handle_file_history_command(args: argparse.Namespace) -> None:
    """Handle the 'sase file-history' command."""
    subcommand = getattr(args, "file_history_subcommand", None)

    if subcommand == "list":
        _handle_list()
    elif subcommand == "delete":
        _handle_delete(args)
    else:
        print("Usage: sase file-history {list,delete}")
        sys.exit(1)


def _handle_list() -> None:
    """Handle 'sase file-history list'."""
    from sase.history.file_references import load_file_references

    print(json.dumps(load_file_references()))
    sys.exit(0)


def _handle_delete(args: argparse.Namespace) -> None:
    """Handle 'sase file-history delete <path>'."""
    from sase.history.file_references import remove_file_reference

    remove_file_reference(args.path)
    sys.exit(0)

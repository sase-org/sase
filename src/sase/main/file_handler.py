"""Handler for the 'sase file' command."""

import argparse
import json
import os
import sys
from dataclasses import asdict


def handle_file_command(args: argparse.Namespace) -> None:
    """Handle the 'sase file' command."""
    subcommand = getattr(args, "file_subcommand", None)

    if subcommand == "list":
        _handle_list(args)
    else:
        print("Usage: sase file {list}")
        sys.exit(1)


def _handle_list(args: argparse.Namespace) -> None:
    """Handle 'sase file list'."""
    from sase.ace.tui.widgets.file_completion import build_completion_candidates

    token = args.token or ""
    # build_completion_candidates needs a token containing '/' (it splits on
    # the last slash to find the directory). If --token is a bare partial
    # like "al" or empty, anchor it to "./" so the listing rooted at --path
    # works after we chdir below.
    if "/" not in token:
        token = f"./{token}"

    saved_cwd = os.getcwd()
    try:
        os.chdir(os.path.expanduser(args.path or "."))
        candidates = build_completion_candidates(token)[0]
    finally:
        os.chdir(saved_cwd)

    print(json.dumps([asdict(c) for c in candidates]))
    sys.exit(0)

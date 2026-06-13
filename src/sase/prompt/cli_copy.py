"""``sase prompt copy`` — copy a stored prompt's exact text to the clipboard."""

from __future__ import annotations

import argparse
import sys

from sase.core.clipboard import copy_to_system_clipboard
from sase.history.prompt import PromptSelectorError, resolve_prompt_selector


def handle_prompt_copy(args: argparse.Namespace) -> None:
    """Copy the exact text of the selected prompt to the system clipboard.

    ``copy`` is an intentional full-text escape hatch (like ``show``). When no
    clipboard command is available it exits nonzero and points at
    ``sase prompt show <id> -f raw`` as a pipe-friendly fallback.
    """
    selector: str = getattr(args, "id", "")

    try:
        record = resolve_prompt_selector(selector)
    except PromptSelectorError as exc:
        print(f"sase prompt copy: {exc}", file=sys.stderr)
        sys.exit(2)

    if not copy_to_system_clipboard(record.text):
        print(
            "sase prompt copy: no system clipboard command available."
            f" Use 'sase prompt show {record.id} -f raw' instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Copied {record.id} ({record.text_chars} chars) to the clipboard.")

"""``sase prompt copy`` — copy a stored prompt to the clipboard."""

from __future__ import annotations

import argparse
import sys

from sase.core.clipboard import copy_to_system_clipboard
from sase.history.prompt import PromptSelectorError, resolve_prompt_selector
from sase.project_display_names import humanize_vcs_refs_in_text


def handle_prompt_copy(args: argparse.Namespace) -> None:
    """Copy display-safe text of the selected prompt to the system clipboard.

    When no clipboard command is available it exits nonzero and points at
    ``sase prompt show <id> -f raw`` as a pipe-friendly canonical fallback.
    """
    selector: str = getattr(args, "id", "")

    try:
        record = resolve_prompt_selector(selector)
    except PromptSelectorError as exc:
        print(f"sase prompt copy: {exc}", file=sys.stderr)
        sys.exit(2)

    text = humanize_vcs_refs_in_text(record.text)
    if not copy_to_system_clipboard(text):
        print(
            "sase prompt copy: no system clipboard command available."
            f" Use 'sase prompt show {record.id} -f raw' instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Copied {record.id} ({len(text)} chars) to the clipboard.")

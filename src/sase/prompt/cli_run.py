"""``sase prompt run``/``edit``/``select`` — replay stored prompts.

These commands reuse the same dispatch path as a fresh ``sase run "<prompt>"``
so foreground/daemon, multi-prompt, multi-model, and xprompt routing stay
identical. ``--prefix`` reuses the existing VCS-tag replacement logic so a
prompt captured under one VCS workflow can be replayed under another without the
compatibility path (``sase run "#vcs:ref ."``) drifting from this one.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from sase.history.prompt import (
    PromptHistoryRecord,
    PromptSelectorError,
    list_prompt_records,
    resolve_prompt_selector,
)
from sase.prompt.render import format_timestamp, prompt_preview


def handle_prompt_run(args: argparse.Namespace) -> None:
    """Launch a stored prompt resolved by selector."""
    record = _resolve_or_exit(getattr(args, "id", ""))
    _replay_record(
        record,
        prefix=getattr(args, "prefix", None),
        edit=bool(getattr(args, "edit", False)),
        daemon=bool(getattr(args, "daemon", False)),
    )


def handle_prompt_edit(args: argparse.Namespace) -> None:
    """Open a stored prompt in the editor, then launch the edited text."""
    record = _resolve_or_exit(getattr(args, "id", ""))
    _replay_record(
        record,
        prefix=getattr(args, "prefix", None),
        edit=True,
        daemon=bool(getattr(args, "daemon", False)),
    )


def handle_prompt_select(args: argparse.Namespace) -> None:
    """Pick a prompt with an fzf picker over the catalog, then launch it."""
    record = _pick_record(
        include_cancelled=bool(getattr(args, "all", False)),
        cancelled_only=bool(getattr(args, "cancelled", False)),
        query=getattr(args, "query", None),
    )
    if record is None:
        # ``_pick_record`` already printed the reason (no history, no fzf, or a
        # cancelled picker). Treat all of these as a clean non-launch.
        sys.exit(1)

    _replay_record(
        record,
        prefix=getattr(args, "prefix", None),
        edit=bool(getattr(args, "edit", False)),
        daemon=bool(getattr(args, "daemon", False)),
    )


def _resolve_or_exit(selector: str) -> PromptHistoryRecord:
    """Resolve a selector to a record, or exit nonzero with a diagnostic."""
    try:
        return resolve_prompt_selector(selector)
    except PromptSelectorError as exc:
        print(f"sase prompt: {exc}", file=sys.stderr)
        sys.exit(2)


def _replay_record(
    record: PromptHistoryRecord,
    *,
    prefix: str | None,
    edit: bool,
    daemon: bool,
) -> None:
    """Apply optional VCS-prefix replacement and editing, then dispatch.

    Prefix replacement happens before editing so the editor shows the prompt as
    it will actually run. An empty edit buffer aborts the launch cleanly.
    """
    text = record.text
    if prefix:
        from sase.xprompt import replace_vcs_workflow_tags

        text = replace_vcs_workflow_tags(text, prefix)

    if edit:
        from sase.main.query_handler._editor import edit_prompt_text

        edited = edit_prompt_text(text)
        if edited is None:
            print("Aborted: empty prompt.", file=sys.stderr)
            sys.exit(1)
        text = edited

    from sase.main.query_handler import dispatch_query

    dispatch_query(text, daemon_mode=daemon)


def _pick_record(
    *,
    include_cancelled: bool,
    cancelled_only: bool,
    query: str | None,
) -> PromptHistoryRecord | None:
    """Run an fzf picker over the filtered catalog and return the chosen record.

    Returns ``None`` when there is nothing to pick, fzf is unavailable, or the
    user cancels the picker. Each of those cases prints a helpful message.
    """
    records = list_prompt_records(
        include_cancelled=include_cancelled,
        cancelled_only=cancelled_only,
        query=query,
        limit=None,
    )
    if not records:
        print("No matching prompts. Try 'sase prompt list -a'.", file=sys.stderr)
        return None

    if shutil.which("fzf") is None:
        print(
            "fzf is not installed. Browse with 'sase prompt list' and launch with"
            " 'sase prompt run <id>'.",
            file=sys.stderr,
        )
        return None

    by_id = {record.id: record for record in records}
    display_lines = "\n".join(
        f"{record.id}  {format_timestamp(record.last_used)}  "
        f"{prompt_preview(record.text)}"
        for record in records
    )

    result = subprocess.run(
        [
            "fzf",
            "--prompt",
            "Select prompt> ",
            "--header",
            "Most recent prompts first",
        ],
        input=display_lines,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # User cancelled (Escape or Ctrl-C).
        print("No prompt selected.", file=sys.stderr)
        return None

    selected = result.stdout.strip()
    if not selected:
        print("No prompt selected.", file=sys.stderr)
        return None

    selected_id = selected.split(maxsplit=1)[0]
    record = by_id.get(selected_id)
    if record is None:
        print("No prompt selected.", file=sys.stderr)
        return None
    return record

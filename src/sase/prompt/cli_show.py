"""``sase prompt show`` — print a stored prompt by selector."""

from __future__ import annotations

import argparse
import json
import sys

from sase.history.prompt import (
    PromptHistoryRecord,
    PromptSelectorError,
    resolve_prompt_selector,
)
from sase.prompt.render import record_to_json


def handle_prompt_show(args: argparse.Namespace) -> None:
    """Resolve the prompt selector and print the requested format."""
    selector: str = getattr(args, "id", "")
    fmt: str = getattr(args, "format", "raw") or "raw"

    try:
        record = resolve_prompt_selector(selector)
    except PromptSelectorError as exc:
        print(f"sase prompt show: {exc}", file=sys.stderr)
        sys.exit(2)

    if fmt == "raw":
        # Exact text, suitable for command substitution or piping. Do not add
        # or strip a trailing newline.
        sys.stdout.write(record.text)
        return
    if fmt == "markdown":
        _print_markdown(record)
        return
    if fmt == "json":
        _print_json(record)
        return

    print(f"sase prompt show: unknown format: {fmt}", file=sys.stderr)
    sys.exit(2)


def _print_markdown(record: PromptHistoryRecord) -> None:
    lines = [
        f"# Prompt {record.id}",
        "",
        f"- id: {record.id}",
        f"- sha256: {record.text_sha256}",
        f"- timestamp: {record.timestamp}",
        f"- last_used: {record.last_used}",
        f"- cancelled: {str(record.cancelled).lower()}",
        f"- chars: {record.text_chars}",
        "",
    ]
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.write(record.text)
    if not record.text.endswith("\n"):
        sys.stdout.write("\n")


def _print_json(record: PromptHistoryRecord) -> None:
    payload = record_to_json(record)
    payload["text"] = record.text
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")

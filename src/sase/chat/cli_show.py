"""``sase chat show`` — print a chat transcript by agent/path/basename."""

from __future__ import annotations

import argparse
import sys

from sase.history.chat import (
    extract_response_from_chat_file,
    load_chat_for_resume,
)
from sase.history.chat_catalog import ChatRefError, resolve_chat_ref
from sase.history.chat_prompt_sections import extract_prompt_renderings


def handle_chat_show(args: argparse.Namespace) -> None:
    """Resolve the chat selector and print the requested format."""
    fmt: str = getattr(args, "format", "raw") or "raw"
    agent: str | None = getattr(args, "agent", None)
    path: str | None = getattr(args, "path", None)
    basename: str | None = getattr(args, "basename", None)

    try:
        resolved_path = resolve_chat_ref(agent=agent, path=path, basename=basename)
    except ChatRefError as exc:
        print(f"sase chat show: {exc}", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError as exc:
        print(f"sase chat show: {exc}", file=sys.stderr)
        sys.exit(2)

    if fmt == "raw":
        _print_raw(resolved_path)
        return
    if fmt == "rendered":
        _print_prompt_rendering(resolved_path, rendered=True)
        return
    if fmt == "resume":
        _print_resume(resolved_path)
        return
    if fmt == "response":
        _print_response(resolved_path)
        return
    if fmt == "xprompt":
        _print_prompt_rendering(resolved_path, rendered=False)
        return

    print(f"sase chat show: unknown format: {fmt}", file=sys.stderr)
    sys.exit(2)


def _print_raw(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            sys.stdout.write(f.read())
    except OSError as exc:
        print(f"sase chat show: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def _print_resume(path: str) -> None:
    try:
        text = load_chat_for_resume(path)
    except (FileNotFoundError, OSError) as exc:
        print(f"sase chat show: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def _print_prompt_rendering(path: str, *, rendered: bool) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            renderings = extract_prompt_renderings(f.read())
    except OSError as exc:
        print(f"sase chat show: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    content = renderings.rendered_prompt if rendered else renderings.xprompt_prompt
    label = "rendered prompt" if rendered else "XPrompt prompt"
    if content is None:
        print(f"sase chat show: no stored {label} found in {path}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(content)
    if not content.endswith("\n"):
        sys.stdout.write("\n")


def _print_response(path: str) -> None:
    response = extract_response_from_chat_file(path)
    if response is None:
        print(
            f"sase chat show: no response could be parsed from {path}",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.stdout.write(response)
    if not response.endswith("\n"):
        sys.stdout.write("\n")

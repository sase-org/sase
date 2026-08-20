"""Handler implementation for the ``sase final`` command group."""

from __future__ import annotations

import argparse
import json
import sys

from sase.finalizers.cli import (
    handle_final_doctor,
    handle_final_list,
    handle_final_show,
)
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    format_context_pretty,
    publish_final_context,
    read_final_manifest_from_path,
    submit_final_manifest,
)


def _handle_context(args: argparse.Namespace) -> int:
    publication = publish_final_context()
    if args.format == "json":
        print(json.dumps(publication.payload, indent=2, sort_keys=True))
    else:
        print(format_context_pretty(publication.payload))
    return 0


def _handle_submit(args: argparse.Namespace) -> int:
    manifest = read_final_manifest_from_path(str(args.manifest))
    payload = submit_final_manifest(manifest)
    validation = payload.get("validation")
    accepted = []
    if isinstance(validation, dict):
        raw = validation.get("accepted_instances")
        if isinstance(raw, list):
            accepted = [str(item) for item in raw]
    if accepted:
        print("Accepted final declaration for: " + ", ".join(accepted))
    else:
        print("Accepted final declaration; no payloads were required.")
    return 0


_DECLARATION_HANDLERS = {
    "context": _handle_context,
    "submit": _handle_submit,
}


def handle_final_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase final ...`` command."""

    subcommand = getattr(args, "final_subcommand", None)
    format_name = getattr(args, "format", "pretty")
    if subcommand in (None, "list"):
        sys.exit(handle_final_list(format_name=format_name))
    if subcommand == "show":
        sys.exit(handle_final_show(args.instance, format_name=format_name))
    if subcommand == "doctor":
        sys.exit(handle_final_doctor(format_name=format_name))

    handler = (
        _DECLARATION_HANDLERS.get(subcommand) if isinstance(subcommand, str) else None
    )
    if handler is None:
        print("Usage: sase final {list,show,doctor,context,submit}", file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(handler(args))
    except FinalizerDeclarationError as exc:
        print(f"sase final {subcommand}: {exc}", file=sys.stderr)
        sys.exit(1)


__all__ = ["handle_final_command"]

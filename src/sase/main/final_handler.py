"""Handler implementation for the ``sase final`` command group."""

from __future__ import annotations

import argparse
from copy import deepcopy
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
    deferrals = _accepted_deferral_summaries(payload)
    if accepted:
        message = "Accepted final declaration for: " + ", ".join(accepted)
        if deferrals:
            message += "; deferred: " + "; ".join(deferrals)
        print(message)
    else:
        print("Accepted final declaration; no payloads were required.")
    return 0


def _handle_defer(args: argparse.Namespace) -> int:
    publication = publish_final_context()
    obligation = next(
        (
            item
            for item in publication.context.obligations
            if item.kind == "repository" and item.obligation_id == args.repo_id
        ),
        None,
    )
    if obligation is None:
        print(
            f"sase final defer: unknown repository obligation {args.repo_id!r}; "
            "run `sase final context` to see current obligations",
            file=sys.stderr,
        )
        return 1
    scope_error = (
        "sase final defer only supports a turn with exactly one finalizer "
        "instance and one dirty repository obligation; use `sase final "
        "context -f json` and `sase final submit` for anything wider"
    )
    manifest = deepcopy(publication.payload["manifest_template"])
    payloads = manifest.get("payloads")
    if not isinstance(payloads, list) or len(payloads) != 1:
        print(f"sase final defer: {scope_error}", file=sys.stderr)
        return 1
    payload = payloads[0].get("payload") if isinstance(payloads[0], dict) else None
    if not isinstance(payload, dict) or not isinstance(
        payload.get("repositories"), list
    ):
        print(f"sase final defer: {scope_error}", file=sys.stderr)
        return 1
    repositories = payload["repositories"]
    if len(repositories) != 1:
        print(f"sase final defer: {scope_error}", file=sys.stderr)
        return 1
    display = obligation.display_name or obligation.obligation_id
    repositories[0]["message"] = f"chore: defer {display} pending review"
    payload["deferrals"].append(
        {
            "repo_id": args.repo_id,
            "reason": args.reason,
            "paths": list(args.paths) if args.paths else list(obligation.paths),
        }
    )
    accepted = submit_final_manifest(manifest)
    print("Deferred: " + "; ".join(_accepted_deferral_summaries(accepted)))
    return 0


def _accepted_deferral_summaries(payload: dict[str, object]) -> list[str]:
    raw = payload.get("accepted_deferrals")
    if not isinstance(raw, list):
        return []
    summaries: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        repo = item.get("repo_display_name") or item.get("repo_id")
        reason = item.get("reason")
        paths = item.get("paths")
        if not isinstance(repo, str) or not isinstance(reason, str):
            continue
        rendered_paths = ""
        if isinstance(paths, list):
            path_values = [str(path) for path in paths[:3]]
            if path_values:
                rendered_paths = " (" + ", ".join(path_values)
                if len(paths) > len(path_values):
                    rendered_paths += f", +{len(paths) - len(path_values)} more"
                rendered_paths += ")"
        summaries.append(f"{repo} {reason}{rendered_paths}")
    return summaries


_DECLARATION_HANDLERS = {
    "context": _handle_context,
    "defer": _handle_defer,
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
        print(
            "Usage: sase final {context,defer,doctor,list,show,submit}",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        sys.exit(handler(args))
    except FinalizerDeclarationError as exc:
        print(f"sase final {subcommand}: {exc}", file=sys.stderr)
        sys.exit(1)


__all__ = ["handle_final_command"]

"""Implementation of ``sase artifact read``."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import cast

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from sase.agent.identity import discover_agent_identity
from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    resolution_error_lines,
    resolved_file_path,
    resolve_cli_reference,
)
from sase.artifact_read_log import (
    ArtifactReadError,
    ArtifactReadEvent,
    append_artifact_read_event,
    artifact_read_log_path,
    build_artifact_read_event,
)
from sase.artifact_refs import render_artifact_ref
from sase.core.artifact_consumption import (
    ArtifactConsumptionResolutionStatus,
    append_artifact_consumption_events,
    artifact_consumption_role,
    build_artifact_consumption_event,
)
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinksDisabledError,
    artifact_links_enabled,
    canonicalize_artifact_link_ref,
    resolve_artifact_link_store,
)
from sase.sdd.frontmatter import parse_frontmatter


_NON_TEXT_POINTER = "Open with `sase artifact open {ref}`."
_READ_NOT_RECORDED = (
    "note: this read was not recorded as a link "
    "(enable `artifact_links` with `sase -f artifact_links` inside an agent run)"
)
_RESOLVED_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})
_TEXT_KINDS = frozenset({"chat", "markdown", "plan", "document"})
_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/toml",
        "application/x-yaml",
        "application/xml",
        "application/yaml",
    }
)


def handle_read(args: argparse.Namespace) -> int:
    """Print an artifact after recording an audited read."""

    try:
        result = resolve_cli_reference(args.reference)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: malformed artifact reference: {exc}", file=sys.stderr)
        return 1

    try:
        body, path, recorded_link = _prepare_body(result)
        _record_audit_and_consumption(
            result, reason=str(args.reason), recorded_link=recorded_link
        )
        if recorded_link:
            try:
                _record_read_link(result, reason=str(args.reason))
            except Exception as exc:  # noqa: BLE001 - still print the artifact
                print(f"Error: could not record read link: {exc}", file=sys.stderr)
        elif not artifact_links_enabled() or not _in_agent_run():
            print(_READ_NOT_RECORDED, file=sys.stderr)
    except ArtifactReadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ArtifactLinksDisabledError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"Error: sase artifact read failed: {exc}", file=sys.stderr)
        return 1

    output_format = str(getattr(args, "format", "markdown") or "markdown")
    line_limit = getattr(args, "lines", None)
    if isinstance(line_limit, int) and line_limit > 0:
        body = "\n".join(body.splitlines()[:line_limit])
        if body and not body.endswith("\n"):
            body += "\n"

    if output_format == "json":
        json.dump(
            {
                "reference": result.canonical_reference,
                "kind": result.parsed.kind,
                "recorded_link": recorded_link,
                "path": None if path is None else str(path),
                "text": body,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    if output_format == "rich":
        _print_rich(result, body)
        return 0
    _print_or_page(body)
    return 0


def _prepare_body(result: ResolvedArtifactReference) -> tuple[str, Path | None, bool]:
    if result.parsed.kind_type in {"stitch", "commit"}:
        return (
            _stitch_body(result),
            result.resolution.resolved_path,
            _should_record_link(),
        )

    path = None
    if result.is_filesystem_backed or result.parsed.kind_type == "file":
        try:
            path = resolved_file_path(result)
        except (ImportError, OSError, RuntimeError, ValueError):
            path = result.resolution.resolved_path

    if path is not None and _is_text_path(path, result):
        text = path.read_text(encoding="utf-8")
        return _strip_managed_text(text), path, _should_record_link()

    if path is not None:
        return _binary_card(result, path), path, _should_record_link()

    if result.resolution.status not in _RESOLVED_STATUSES:
        raise ArtifactReadError("\n".join(resolution_error_lines(result)))
    return _binary_card(result, path), path, _should_record_link()


def _strip_managed_text(text: str) -> str:
    stripped = str(require_rust_binding("links_block_strip")(text))
    stripped = str(require_rust_binding("referenced_by_block_strip")(stripped))
    _frontmatter, body, had_frontmatter = parse_frontmatter(stripped)
    return body if had_frontmatter else stripped


def _stitch_body(result: ResolvedArtifactReference) -> str:
    properties: dict[str, str] = {}
    if result.entry is not None:
        properties = dict(result.entry.properties)
    lines = [
        f"kind: {result.parsed.kind}",
        f"reference: {result.canonical_reference}",
        f"status: {result.resolution.status}",
        f"locator: {result.resolution.locator or '-'}",
        f"subject: {properties.get('subject') or '-'}",
        f"author: {properties.get('author') or '-'}",
        f"repo: {properties.get('repo') or '-'}",
        f"sha: {properties.get('sha') or '-'}",
    ]
    return "\n".join(lines) + "\n"


def _binary_card(result: ResolvedArtifactReference, path: Path | None) -> str:
    kind = result.file.kind if result.file is not None else result.parsed.kind
    mime = result.file.mime_type if result.file is not None else None
    lines = [
        f"kind: {kind}",
        f"reference: {result.canonical_reference}",
        f"mime_type: {mime or '-'}",
        f"path: {path if path is not None else '-'}",
        _NON_TEXT_POINTER.format(ref=result.canonical_reference),
    ]
    return "\n".join(lines) + "\n"


def _record_audit_and_consumption(
    result: ResolvedArtifactReference,
    *,
    reason: str,
    recorded_link: bool,
) -> None:
    canonical = render_artifact_ref(replace(result.parsed, fragment=None))
    event: ArtifactReadEvent = build_artifact_read_event(
        ref=canonical,
        reason=reason,
        recorded_link=recorded_link,
    )
    append_artifact_read_event(event, log_path=artifact_read_log_path(event.project))
    if result.resolution.status not in _RESOLVED_STATUSES:
        return
    fragment = None
    if result.parsed.fragment is not None:
        fragment = result.canonical_reference[len(canonical) + 1 :]
    artifact_id = None
    if (
        result.parsed.kind_type == "file"
        and result.parsed.payload.source is not None
        and result.parsed.payload.digest is not None
    ):
        artifact_id = f"{result.parsed.payload.source}:{result.parsed.payload.digest}"
    path = result.resolution.resolved_path
    status = result.resolution.status
    if status not in {"exact", "drifted", "vcs_backed"}:
        return
    consumption = build_artifact_consumption_event(
        ref=canonical,
        ref_kind=result.parsed.kind,
        fragment=fragment,
        role=artifact_consumption_role(
            result.parsed.kind_type, result.parsed.kind, path
        ),
        artifact_id=artifact_id,
        resolved_path=path,
        resolution_status=cast(ArtifactConsumptionResolutionStatus, status),
    )
    try:
        append_artifact_consumption_events((consumption,))
    except OSError as exc:
        raise ArtifactReadError(
            f"could not record artifact consumption event: {exc}"
        ) from exc


def _record_read_link(result: ResolvedArtifactReference, *, reason: str) -> None:
    identity = discover_agent_identity()
    if identity is None:
        return
    store = resolve_artifact_link_store()
    target = canonicalize_artifact_link_ref(
        render_artifact_ref(replace(result.parsed, fragment=None))
    )
    source = f"agent:{identity.name}"
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": source,
            "relation": "read",
            "target_ref": target,
            "description": reason,
            "origin": "read",
            "created_by": identity.name,
            "created_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uses": 1,
        }
    )


def _should_record_link() -> bool:
    return bool(
        artifact_links_enabled() and _in_agent_run() and discover_agent_identity()
    )


def _in_agent_run() -> bool:
    return bool(os.environ.get("SASE_AGENT"))


def _is_text_path(path: Path, result: ResolvedArtifactReference) -> bool:
    kind = result.file.kind if result.file is not None else result.parsed.kind
    mime = result.file.mime_type if result.file is not None else None
    if kind in _TEXT_KINDS or result.parsed.kind_type in {"chat", "document"}:
        return True
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".xml", ".rst"}:
        return True
    if mime is None:
        return suffix in {".py", ".sh", ".toml"}
    return mime.startswith(_TEXT_MIME_PREFIXES) or mime in _TEXT_MIME_TYPES


def _print_rich(result: ResolvedArtifactReference, body: str) -> None:
    console = Console()
    console.print(
        Panel(
            Markdown(body) if body.strip() else "[dim](empty)[/dim]",
            title=result.canonical_reference,
            border_style="cyan",
        )
    )


def _print_or_page(body: str) -> None:
    if not sys.stdout.isatty():
        sys.stdout.write(body if body.endswith("\n") else body + "\n")
        return
    pager = shutil.which("less") or shutil.which("bat")
    if pager is None:
        sys.stdout.write(body if body.endswith("\n") else body + "\n")
        return
    command = (
        [pager, "-R", "-F"]
        if Path(pager).name == "less"
        else [pager, "--paging=always", "--color=always", "--style=plain"]
    )
    try:
        completed = subprocess.run(command, input=body, text=True, check=False)
    except OSError:
        sys.stdout.write(body if body.endswith("\n") else body + "\n")
        return
    if completed.returncode != 0:
        sys.stdout.write(body if body.endswith("\n") else body + "\n")


__all__ = ["handle_read"]

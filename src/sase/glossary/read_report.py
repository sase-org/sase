"""Markdown reports for audited ``sase glossary read`` invocations.

Frontend-agnostic on purpose: ACE hint selection materializes these reports,
and any other surface can reuse the same builder.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import shlex
import tempfile
from pathlib import Path

from sase.core.paths import ensure_sase_directory, sase_subdir
from sase.core.time import format_local
from sase.glossary.cli_common import (
    GlossaryCliError,
    ResolvedGlossaryProject,
    resolve_glossary_cli_project,
    resolve_glossary_cli_project_name,
)
from sase.glossary.read_log import GlossaryReadEvent
from sase.glossary.render import glossary_closure_markdown
from sase.glossary.resolution import (
    GlossaryClosure,
    GlossaryLookupError,
    resolve_glossary_closure,
)

_REPORT_SUBDIR = "glossary_read_reports"
_REPORT_KEEP_COUNT = 50


@dataclass(frozen=True)
class GlossaryReadReportSpec:
    """Deferred report write request for one glossary read."""

    event: GlossaryReadEvent
    agent_label: str | None
    report_path: str


def glossary_read_report_path(event: GlossaryReadEvent) -> str:
    """Return the deterministic report path for ``event`` without writing."""
    slug = _safe_filename(event.terms[0] if event.terms else "glossary")
    hhmmss = format_local(event.timestamp, "%H%M%S", default="unknown")
    digest = hashlib.sha256(event.id.encode("utf-8")).hexdigest()[:8]
    return str(sase_subdir(_REPORT_SUBDIR) / f"{slug}-{hhmmss}-{digest}.md")


def _build_glossary_read_report(spec: GlossaryReadReportSpec) -> str:
    """Render one glossary-read report as Markdown.

    Never raises for missing projects, unknown terms, or catalog I/O: those
    degrade to the recorded-metadata block plus a short note.
    """
    event = spec.event
    resolved: ResolvedGlossaryProject | None = None
    closure: GlossaryClosure | None = None
    failure_note: str | None = None
    try:
        resolved = resolve_glossary_cli_project(event.project)
        closure = resolve_glossary_closure(
            resolved.catalog,
            resolved.compiled,
            event.terms,
            depth=event.depth_limit,
        )
    except GlossaryCliError as exc:
        failure_note = f"Could not resolve this project's glossary: {exc}"
    except GlossaryLookupError as exc:
        failure_note = f"Could not re-resolve the glossary closure: {exc}"
    except OSError as exc:
        failure_note = f"Could not load the glossary: {exc}"

    project_name = _project_display_name(event, resolved)
    lines: list[str] = [
        f"# Glossary read: {_title_terms(event)}",
        "",
        "```",
        _reproduced_command(event),
        "```",
        "",
        "## Recorded",
        "",
        *_metadata_lines(spec, project_name=project_name),
        "",
    ]
    if failure_note is not None:
        recorded = ", ".join(event.terms) if event.terms else "(none)"
        lines.extend(
            [
                "## Note",
                "",
                failure_note,
                "",
                f"Recorded terms: {recorded}",
                "",
            ]
        )
        return _join_markdown(lines)

    assert resolved is not None and closure is not None
    lines.extend(
        [
            "## Output",
            "",
            glossary_closure_markdown(
                closure, project_name=resolved.project_name
            ).rstrip(),
            "",
        ]
    )
    related_now = sum(1 for node in closure.nodes if node.origin == "related")
    recorded_related = len(event.related_terms)
    if related_now != recorded_related:
        recorded_word = "term" if recorded_related == 1 else "terms"
        current_word = "term" if related_now == 1 else "terms"
        lines.extend(
            [
                f"Note: this read recorded {recorded_related} related "
                f"{recorded_word}; the current glossary has {related_now} "
                f"related {current_word}.",
                "",
            ]
        )
    return _join_markdown(lines)


def write_glossary_read_report(spec: GlossaryReadReportSpec) -> str | None:
    """Write a glossary-read report atomically and return its path."""
    try:
        report_dir = Path(ensure_sase_directory(_REPORT_SUBDIR))
        report_path = Path(spec.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        content = _build_glossary_read_report(spec)
        tmp_path = _write_atomic(report_path, content)
        os.replace(tmp_path, report_path)
        _prune_reports(report_dir)
        return str(report_path)
    except OSError:
        return None


def _project_display_name(
    event: GlossaryReadEvent, resolved: ResolvedGlossaryProject | None
) -> str | None:
    if resolved is not None:
        return resolved.project_name
    try:
        return resolve_glossary_cli_project_name(event.project)
    except GlossaryCliError:
        return None


def _title_terms(event: GlossaryReadEvent) -> str:
    return ", ".join(event.terms) if event.terms else "(no terms)"


def _reproduced_command(event: GlossaryReadEvent) -> str:
    parts = ["sase", "glossary", "read", *event.terms]
    if event.depth_limit is not None:
        parts.extend(["-d", str(event.depth_limit)])
    parts.extend(["-r", event.reason])
    return " ".join(shlex.quote(part) for part in parts)


def _metadata_lines(
    spec: GlossaryReadReportSpec, *, project_name: str | None
) -> list[str]:
    event = spec.event
    agent = event.agent_name
    if spec.agent_label:
        agent = f"{agent} ({spec.agent_label})"
    depth = "unlimited" if event.depth_limit is None else str(event.depth_limit)
    source = event.source_path or "(none recorded)"
    requested = ", ".join(event.terms) if event.terms else "(none)"
    return [
        f"- **Time**: {format_local(event.timestamp)}",
        f"- **Agent**: {agent}",
        f"- **Project**: {project_name or '(unresolved)'}",
        f"- **Reason**: {event.reason}",
        f"- **Requested terms**: {requested}",
        f"- **Related terms**: {len(event.related_terms)}",
        f"- **Depth limit**: {depth}",
        f"- **Definition bytes**: {event.definition_bytes}",
        f"- **Source**: {source}",
    ]


def _join_markdown(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


def _write_atomic(path: Path, content: str) -> str:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return tmp_name


def _prune_reports(report_dir: Path) -> None:
    reports = sorted(
        report_dir.glob("*.md"),
        key=lambda path: (_mtime_ns(path), path.name),
        reverse=True,
    )
    for path in reports[_REPORT_KEEP_COUNT:]:
        try:
            path.unlink()
        except OSError:
            pass


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return safe or "glossary"


__all__ = [
    "GlossaryReadReportSpec",
    "glossary_read_report_path",
    "write_glossary_read_report",
]

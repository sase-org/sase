"""Markdown reports for modern audited memory-read selector batches.

Frontend-agnostic on purpose: ACE hint selection materializes these reports,
and any other surface can reuse the same builder.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import shlex
from pathlib import Path

from sase.core.paths import ensure_sase_directory, sase_subdir
from sase.core.time import format_local
from sase.memory.atomic_write import write_bytes_atomically
from sase.memory.read_log import MemoryReadError, MemoryReadEvent
from sase.memory.selector import (
    ResolvedMemorySelectorBatch,
    resolve_memory_selector_batch,
)
from sase.memory.selector_render import memory_selector_batch_markdown

_REPORT_SUBDIR = "memory_read_reports"
_REPORT_KEEP_COUNT = 50


@dataclass(frozen=True)
class MemoryReadReportSpec:
    """Deferred report write request for one modern memory read."""

    event: MemoryReadEvent
    agent_label: str | None
    report_path: str


def memory_read_report_path(event: MemoryReadEvent) -> str:
    """Return the deterministic report path for ``event`` without writing."""
    selector = _report_slug_seed(event)
    slug = _safe_filename(selector)
    hhmmss = format_local(event.timestamp, "%H%M%S", default="unknown")
    digest = hashlib.sha256(event.id.encode("utf-8")).hexdigest()[:8]
    return str(sase_subdir(_REPORT_SUBDIR) / f"{slug}-{hhmmss}-{digest}.md")


def _build_memory_read_report(spec: MemoryReadReportSpec) -> str:
    """Render one memory-read report as Markdown.

    Resolution failures degrade to recorded metadata plus a short note. The
    report is intentionally non-auditing: it resolves the equivalent
    ``memory show`` view and never appends a memory-read event.
    """
    event = spec.event
    selectors = _event_selectors(event)
    output: str | None = None
    failure_note: str | None = None
    try:
        view = _resolve_report_view(event, selectors)
        output = memory_selector_batch_markdown(view).rstrip()
    except (MemoryReadError, OSError, UnicodeError, RuntimeError, ValueError) as exc:
        failure_note = f"Could not re-resolve the memory selector batch: {exc}"

    lines: list[str] = [
        f"# Memory read: {_title_selectors(selectors)}",
        "",
        "```",
        _reproduced_command(event, selectors),
        "```",
        "",
        "## Recorded",
        "",
        *_metadata_lines(spec, selectors=selectors),
        "",
    ]
    if failure_note is not None:
        lines.extend(
            [
                "## Note",
                "",
                failure_note,
                "",
                f"Recorded selectors: {_title_selectors(selectors)}",
                "",
            ]
        )
        return _join_markdown(lines)

    lines.extend(
        [
            "## Output",
            "",
            output or "",
            "",
        ]
    )
    return _join_markdown(lines)


def write_memory_read_report(spec: MemoryReadReportSpec) -> str | None:
    """Write a memory-read report atomically and return its path."""
    try:
        report_dir = Path(ensure_sase_directory(_REPORT_SUBDIR))
        report_path = Path(spec.report_path)
        content = _build_memory_read_report(spec)
        write_bytes_atomically(
            report_path,
            content.encode("utf-8"),
            overwrite=True,
        )
        _prune_reports(report_dir)
        return str(report_path)
    except OSError:
        return None


def _resolve_report_view(
    event: MemoryReadEvent,
    selectors: tuple[str, ...],
) -> ResolvedMemorySelectorBatch:
    event_cwd = Path(event.cwd).expanduser() if event.cwd else None
    home_root = Path.home()
    try:
        return resolve_memory_selector_batch(
            list(selectors),
            depth=event.depth,
            project_ref=event.project or None,
            project_root=event_cwd,
            home_root=home_root,
        )
    except MemoryReadError:
        if event_cwd is None:
            raise
        return resolve_memory_selector_batch(
            list(selectors),
            depth=event.depth,
            project_ref=None,
            project_root=event_cwd,
            home_root=home_root,
        )


def _event_selectors(event: MemoryReadEvent) -> tuple[str, ...]:
    if event.selectors:
        return event.selectors
    if event.canonical_path:
        return (event.canonical_path,)
    return ()


def _metadata_lines(
    spec: MemoryReadReportSpec,
    *,
    selectors: tuple[str, ...],
) -> list[str]:
    event = spec.event
    agent = event.agent_name
    if spec.agent_label:
        agent = f"{agent} ({spec.agent_label})"
    depth = "unlimited" if event.depth is None else str(event.depth)
    resolved = ", ".join(event.resolved_targets) if event.resolved_targets else "(none)"
    included = ", ".join(event.included_targets) if event.included_targets else "(none)"
    scope_origin = (
        ", ".join(f"{target}={scope}" for target, scope in event.scope_origin)
        if event.scope_origin
        else "(none)"
    )
    return [
        f"- **Time**: {format_local(event.timestamp)}",
        f"- **Agent**: {agent}",
        f"- **Project**: {event.project or '(unresolved)'}",
        f"- **CWD**: {event.cwd or '(none recorded)'}",
        f"- **Reason**: {event.reason}",
        f"- **Kind**: {event.kind}",
        f"- **Selectors**: {_title_selectors(selectors)}",
        f"- **Resolved targets**: {resolved}",
        f"- **Included targets**: {included}",
        f"- **Depth limit**: {depth}",
        f"- **Scope origin**: {scope_origin}",
        f"- **Definition bytes**: {event.byte_count}",
        f"- **Frontmatter stripped**: {event.frontmatter_stripped}",
    ]


def _reproduced_command(event: MemoryReadEvent, selectors: tuple[str, ...]) -> str:
    parts = ["sase", "memory", "show"]
    if event.project:
        parts.extend(["-p", event.project])
    parts.extend(selectors)
    if event.depth is not None:
        parts.extend(["-d", str(event.depth)])
    parts.extend(["--format", "markdown"])
    return " ".join(shlex.quote(part) for part in parts)


def _title_selectors(selectors: tuple[str, ...]) -> str:
    return ", ".join(selectors) if selectors else "(no selectors)"


def _report_slug_seed(event: MemoryReadEvent) -> str:
    selectors = _event_selectors(event)
    if selectors:
        return selectors[0]
    return event.kind or "memory"


def _join_markdown(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


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
    return safe or "memory"


__all__ = [
    "MemoryReadReportSpec",
    "memory_read_report_path",
    "write_memory_read_report",
]

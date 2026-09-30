"""Scan, resolve, ingest, and name assignment for note attachments."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.attachments.ingest import IngestError, ingest_path

from ._authoring_models import NoteAttachmentAuthoringError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sase.bead.attachments.progress import ProgressFactory

_MISSING_FILE_HINT = "Write @@… for literal text, or fix the path."
_SENSITIVE_HINT = "pass -S/--allow-sensitive to attach it anyway"


def scan_resolve_ingest(
    text: str,
    roster_names: list[str],
    cwd: Path | str | None,
    allow_sensitive: bool,
    progress_factory: ProgressFactory | None = None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[int, Path],
    dict[Path, Any],
    Path,
]:
    """Scan *text*, resolve every path ref, and ingest each unique path once."""
    from sase.core.rust import require_rust_binding

    scan_binding = require_rust_binding("scan_note_attachment_refs")
    base_dir = Path(cwd) if cwd is not None else Path.cwd()
    scan: dict[str, Any] = dict(scan_binding(text, list(roster_names)))
    path_refs: list[dict[str, Any]] = list(scan.get("path_refs") or [])
    reuse_refs: list[dict[str, Any]] = list(scan.get("reuse_refs") or [])
    problems: list[str] = [
        _caret_problem(text, dict(diag))
        for diag in (scan.get("diagnostics") or [])
        if isinstance(diag, dict)
    ]
    resolved = _resolve_path_refs(text, path_refs, base_dir, allow_sensitive, problems)
    if problems:
        raise NoteAttachmentAuthoringError(_problems_message(problems))
    blobs = _ingest_unique_paths(text, path_refs, resolved, progress_factory)
    return scan, path_refs, reuse_refs, resolved, blobs, base_dir


def assign_names(
    resolved: dict[int, Path],
    blobs: dict[Path, Any],
    roster: Mapping[str, dict[str, Any]],
    path_refs: list[dict[str, Any]],
    preferred_names: Mapping[str, str] | None = None,
) -> tuple[dict[int, str], dict[int, str]]:
    """Map each resolved path-ref index to its name and echo display base.

    Returns the assigned names plus, per index, the raw base the echo row
    compares against (the preferred name when given, else the file basename).
    """
    from sase.core.rust import require_rust_binding

    sanitize_binding = require_rust_binding("sanitize_attachment_name")
    unique_binding = require_rust_binding("unique_attachment_name")
    existing = [
        {"name": name, "sha256": wire["sha256"]} for name, wire in roster.items()
    ]
    assigned: dict[int, str] = {}
    display_bases: dict[int, str] = {}
    seen_targets: dict[Path, tuple[str, str]] = {}
    for index in sorted(resolved):
        target = resolved[index]
        if target in seen_targets:
            assigned[index], display_bases[index] = seen_targets[target]
            continue
        raw = str(path_refs[index].get("path") or "")
        base = (preferred_names or {}).get(raw, target.name)
        candidate = str(sanitize_binding(base))
        name = str(unique_binding(candidate, blobs[target].sha256, existing))
        seen_targets[target] = (name, base)
        assigned[index] = name
        display_bases[index] = base
        existing.append({"name": name, "sha256": blobs[target].sha256})
    return assigned, display_bases


def _resolve_path_refs(
    text: str,
    path_refs: list[dict[str, Any]],
    base_dir: Path,
    allow_sensitive: bool,
    problems: list[str],
) -> dict[int, Path]:
    """Resolve every path ref, collecting problems without raising."""
    from sase.core.rust import require_rust_binding

    sensitive_binding = require_rust_binding("attachment_sensitive_path_reason")
    resolved: dict[int, Path] = {}
    home = str(Path.home())
    extra_patterns: list[str] | None = None
    for index, ref in enumerate(path_refs):
        raw = str(ref.get("path") or "")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        target = candidate.resolve()
        if not target.exists():
            problems.append(
                _caret_problem(
                    text,
                    {
                        "span": ref.get("span") or {"start": 0, "end": 0},
                        "message": f"@{raw}: file not found",
                        "hint": _MISSING_FILE_HINT,
                    },
                )
            )
            continue
        if target.is_dir():
            problems.append(
                _caret_problem(
                    text,
                    {
                        "span": ref.get("span") or {"start": 0, "end": 0},
                        "message": (
                            f"@{raw}: it is a directory (hint: "
                            "`tar czf dir.tar.gz dir/` then attach the archive)"
                        ),
                        "hint": "",
                    },
                )
            )
            continue
        if not allow_sensitive:
            if extra_patterns is None:
                from sase.bead.config import get_attachment_sensitive_patterns

                extra_patterns = get_attachment_sensitive_patterns()
            reason = sensitive_binding(str(target), home, extra_patterns)
            if reason is not None:
                problems.append(
                    _caret_problem(
                        text,
                        {
                            "span": ref.get("span") or {"start": 0, "end": 0},
                            "message": f"@{raw}: {reason}",
                            "hint": (f"Refusing to attach it; {_SENSITIVE_HINT}."),
                        },
                    )
                )
                continue
        resolved[index] = target
    return resolved


def _ingest_unique_paths(
    text: str,
    path_refs: list[dict[str, Any]],
    resolved: dict[int, Path],
    progress_factory: ProgressFactory | None = None,
) -> dict[Path, Any]:
    """Ingest each unique resolved path once, in first-seen order.

    A failure raises one combined error and writes no bead event.
    *progress_factory* draws a TTY bar per file when given.
    """
    unique: list[Path] = []
    for index in sorted(resolved):
        target = resolved[index]
        if target not in unique:
            unique.append(target)
    blobs: dict[Path, Any] = {}
    problems: list[str] = []
    for target in unique:
        try:
            if progress_factory is None:
                blobs[target] = ingest_path(str(target))
            else:
                try:
                    total = target.stat().st_size
                except OSError:
                    total = None
                with progress_factory(target.name, total) as bar:
                    blobs[target] = ingest_path(str(target), progress=bar)
        except IngestError as exc:
            first = next(index for index, path in resolved.items() if path == target)
            problems.append(
                _caret_problem(
                    text,
                    {
                        "span": path_refs[first].get("span") or {"start": 0, "end": 0},
                        "message": f"{target}: {exc}",
                        "hint": "",
                    },
                )
            )
    if problems:
        raise NoteAttachmentAuthoringError(_problems_message(problems))
    return blobs


def _caret_problem(text: str, problem: Mapping[str, Any]) -> str:
    """Render one problem with a caret line under the offending span."""
    span = problem.get("span")
    start = span.get("start", 0) if isinstance(span, dict) else 0
    end = span.get("end", 0) if isinstance(span, dict) else 0
    line, column, width = _caret_position(text, start, end)
    message = str(problem.get("message") or "invalid reference")
    hint = str(problem.get("hint") or "").strip()
    block = f"{line}\n{' ' * column}{'^' * width} {message}"
    if hint:
        block += f"\n{' ' * column}  {hint}"
    return block


def _caret_position(text: str, start: int, end: int) -> tuple[str, int, int]:
    """Locate the display column and width of byte-offset span ``[start, end)``."""
    from rich.cells import cell_len

    data = text.encode("utf-8")
    start = max(0, min(start, len(data)))
    end = max(start, min(end, len(data)))
    line_start = data.rfind(b"\n", 0, start) + 1
    line_end = data.find(b"\n", start)
    if line_end < 0:
        line_end = len(data)
    end = min(end, line_end)
    line = data[line_start:line_end].decode("utf-8", errors="replace")
    prefix = data[line_start:start].decode("utf-8", errors="replace")
    span_text = data[start:end].decode("utf-8", errors="replace")
    return line, cell_len(prefix), max(1, cell_len(span_text))


def _problems_message(problems: list[str]) -> str:
    """Combine problems under the pluralized nothing-was-written header."""
    count = len(problems)
    noun = "problem" if count == 1 else "problems"
    header = f"{count} attachment {noun} in note text — nothing was written."
    return header + "\n\n" + "\n\n".join(problems)

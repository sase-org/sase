"""Shared authoring service for bead note attachments (beta).

One pipeline, used by the CLI note verbs and the TUI add-note modal::

    1. Scan the text with the bead's current roster names.
    2. Resolve and stat every referenced path; apply the sensitive-path policy.
    3. Raise one error for every scanner diagnostic and resolution problem.
    4. Ingest each unique resolved path once.
    5. Classify, probe images, and record the machine origin.
    6. Uniquify names against the roster plus this text, then compose.

It returns the stored text, the wire manifest, echo rows, and the names the
edit detached. Nothing is written to the bead store: callers pass the
manifest into the mutation only after this returns. Import this module only
when the ``bead_note_attachments`` flag is on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.attachments.ingest import IngestError, ingest_path

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sase.bead.model import BeadNote

#: Echo rows starting with this prefix are dim hints, not attached files.
HINT_ROW_PREFIX = "hint: "

_MISSING_FILE_HINT = "Write @@… for literal text, or fix the path."
_SENSITIVE_HINT = "pass -S/--allow-sensitive to attach it anyway"
_EPS_SUFFIXES = frozenset({".eps", ".epsi", ".epsf"})


class NoteAttachmentAuthoringError(ValueError):
    """One or more attachment problems in note text; nothing was written."""


@dataclass(frozen=True)
class AuthoredNoteAttachments:
    """The result of running the authoring pipeline over note text."""

    stored_text: str
    #: ``BeadNoteAttachmentWire`` dicts to persist with the note.
    attachments: list[dict[str, Any]] = field(default_factory=list)
    #: stderr rows for the write echo. Rows starting with ``"hint: "`` are
    #: dim hints; the rest name attached or detached files.
    echo_rows: list[str] = field(default_factory=list)
    #: Previous-manifest names absent from the new manifest (edits only).
    detached: tuple[str, ...] = ()


def author_note_attachments(
    text: str,
    *,
    notes: Sequence[BeadNote] = (),
    cwd: Path | str | None = None,
    allow_sensitive: bool = False,
    previous_manifest: Sequence[str] = (),
) -> AuthoredNoteAttachments:
    """Scan *text*, ingest referenced files, and compose the stored note."""
    from sase.core.rust import require_rust_binding

    scan_binding = require_rust_binding("scan_note_attachment_refs")
    base_dir = Path(cwd) if cwd is not None else Path.cwd()
    roster = _roster_wires(notes)
    scan: dict[str, Any] = dict(scan_binding(text, list(roster)))
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
    blobs = _ingest_unique_paths(text, path_refs, resolved)
    assigned = _assign_names(resolved, blobs, roster)
    assigned_names = [assigned[index] for index in range(len(path_refs))]
    compose_binding = require_rust_binding("compose_note_attachment_text")
    stored_text = str(compose_binding(text, scan, assigned_names))
    manifest, echo_rows = _build_manifest(resolved, blobs, assigned, reuse_refs, roster)
    new_names = [wire["name"] for wire in manifest]
    detached = tuple(name for name in previous_manifest if name not in new_names)
    for name in detached:
        echo_rows.append(f"detached {name}")
    echo_rows.extend(_bare_word_hints(scan, base_dir))
    return AuthoredNoteAttachments(
        stored_text=stored_text,
        attachments=manifest,
        echo_rows=echo_rows,
        detached=detached,
    )


def _roster_wires(notes: Sequence[BeadNote]) -> dict[str, dict[str, Any]]:
    """Map each roster name to its latest wire dict.

    The latest note wins per name, matching sase-core's
    ``bead_attachment_roster`` over the current notes.
    """
    roster: dict[str, dict[str, Any]] = {}
    for note in notes:
        for attachment in note.attachments:
            wire: dict[str, Any] = {
                "name": attachment.name,
                "sha256": attachment.sha256,
                "size_bytes": attachment.size_bytes,
                "mime_type": attachment.mime_type,
            }
            if attachment.image is not None:
                wire["image"] = {
                    "width": attachment.image[0],
                    "height": attachment.image[1],
                }
            if attachment.origin is not None:
                wire["origin"] = attachment.origin
            roster[attachment.name] = wire
    return roster


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
) -> dict[Path, Any]:
    """Ingest each unique resolved path once, in first-seen order.

    A failure raises one combined error and writes no bead event.
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
            blobs[target] = ingest_path(str(target))
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


def _assign_names(
    resolved: dict[int, Path],
    blobs: dict[Path, Any],
    roster: Mapping[str, dict[str, Any]],
) -> dict[int, str]:
    """Map each resolved path-ref index to its assigned attachment name."""
    from sase.core.rust import require_rust_binding

    sanitize_binding = require_rust_binding("sanitize_attachment_name")
    unique_binding = require_rust_binding("unique_attachment_name")
    existing = [
        {"name": name, "sha256": wire["sha256"]} for name, wire in roster.items()
    ]
    assigned: dict[int, str] = {}
    seen_targets: dict[Path, str] = {}
    for index in sorted(resolved):
        target = resolved[index]
        if target in seen_targets:
            assigned[index] = seen_targets[target]
            continue
        candidate = str(sanitize_binding(target.name))
        name = str(unique_binding(candidate, blobs[target].sha256, existing))
        seen_targets[target] = name
        assigned[index] = name
        existing.append({"name": name, "sha256": blobs[target].sha256})
    return assigned


def _build_manifest(
    resolved: dict[int, Path],
    blobs: dict[Path, Any],
    assigned: dict[int, str],
    reuse_refs: list[dict[str, Any]],
    roster: Mapping[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build the wire manifest and echo rows for new ingests and reuses."""
    from sase.config import get_machine_name
    from sase.core.rust import require_rust_binding

    classify_binding = require_rust_binding("classify_attachment")
    sanitize_binding = require_rust_binding("sanitize_attachment_name")
    manifest: list[dict[str, Any]] = []
    echo_rows: list[str] = []
    seen_names: set[str] = set()
    seen_targets: set[Path] = set()
    origin = get_machine_name() or None
    for index in sorted(resolved):
        target = resolved[index]
        name = assigned[index]
        if target not in seen_targets:
            seen_targets.add(target)
            blob = blobs[target]
            classified: dict[str, Any] = dict(classify_binding(name, bytes(blob.head)))
            wire: dict[str, Any] = {
                "name": name,
                "sha256": blob.sha256,
                "size_bytes": blob.size_bytes,
                "mime_type": str(classified.get("mime_type") or ""),
            }
            dims = _probe_image_dims(name, blob.object_path)
            if dims is not None:
                wire["image"] = {"width": dims[0], "height": dims[1]}
            if origin:
                wire["origin"] = origin
            manifest.append(wire)
            seen_names.add(name)
            sanitized = str(sanitize_binding(target.name))
            size = _format_size(blob.size_bytes)
            descriptor = wire["mime_type"]
            if dims is not None:
                descriptor += f" · {dims[0]}×{dims[1]}"
            if name == sanitized:
                echo_rows.append(f"attached {name} · {descriptor} · {size} · local")
            else:
                echo_rows.append(
                    f"{sanitized} stored as {name} · {descriptor} · {size} · local"
                )
    for ref in reuse_refs:
        name = str(ref.get("name") or "")
        if name in seen_names or name not in roster:
            continue
        seen_names.add(name)
        manifest.append(dict(roster[name]))
    return manifest, echo_rows


def _probe_image_dims(name: str, object_path: object) -> tuple[int, int] | None:
    """Probe pixel dimensions, never raising and never for SVG/EPS."""
    if Path(name).suffix.lower() in _EPS_SUFFIXES:
        return None
    from sase.bead.attachments.images import probe_image

    dims = probe_image(object_path)  # type: ignore[arg-type]
    if dims is None:
        return None
    return (dims.width, dims.height)


def _bare_word_hints(
    scan: Mapping[str, Any],
    base_dir: Path,
) -> list[str]:
    """Dim hints for bare-word mentions whose ``./word`` file exists."""
    hints: list[str] = []
    bare_words = scan.get("bare_words") or []
    for entry in bare_words:
        if not isinstance(entry, dict):
            continue
        word = str(entry.get("word") or "")
        if not word:
            continue
        try:
            is_file = (base_dir / word).is_file()
        except OSError:
            continue
        if not is_file:
            continue
        hints.append(
            f"{HINT_ROW_PREFIX}@{word} looks like text, but ./{word} "
            f"exists — write @./{word} to attach it"
        )
    return hints


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


def _format_size(size_bytes: int) -> str:
    """Format a byte count the way the write echo does."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    return f"{size_bytes / (1024 * 1024):g} MiB"

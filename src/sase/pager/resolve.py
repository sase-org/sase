"""Resolve a followed ref into a target the pager can land on.

D6's single narrow interface (``resolve_ref``), backed by the same CLI
reference resolution ``sase artifact read``/``sase bead show`` already use.
This module does real I/O — filesystem stats, bead-store reads, VCS
materialization — so it must never run on the UI thread. ``SasePager``
dispatches it through ``asyncio.to_thread`` inside a pump-free task with a
generation check (see ``app.py``); the resolution itself stays synchronous
and side-effect free here so it is trivially testable without booting Textual.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sase.ace.tui.graphics import ArtifactFileViewSpec, artifact_file_view_mode
from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    resolve_cli_reference,
    resolved_file_path,
)
from sase.artifact_ref_models import ArtifactRefFragment
from sase.artifact_ref_operations import parse_artifact_ref
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager.adapters import path_section
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_scan import LinkSpanKind

log = logging.getLogger(__name__)

_RESOLVED_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})
_MEDIA_MODES = frozenset({"image", "video", "pdf"})
_TEXT_SUFFIXES = frozenset(
    {".md", ".markdown", ".txt", ".json", ".yml", ".yaml", ".toml", ".xml", ".rst"}
)
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


class LinkTargetKind(StrEnum):
    """What kind of thing a press should do (design doc section D6)."""

    DOCUMENT = "document"
    MEDIA = "media"


@dataclass(frozen=True, slots=True)
class LinkTarget:
    """One resolved press destination.

    ``edit_path``/``edit_line`` are populated whenever a real file backs the
    target, independent of ``kind`` — this is what lets the one-shot ``E``
    prefix (design doc D8) reuse the same resolution as a normal follow.
    """

    kind: LinkTargetKind
    document: PagerDocument | None = None
    scroll_line: int | None = None
    media_specs: tuple[ArtifactFileViewSpec, ...] = ()
    edit_path: Path | None = None
    edit_line: int | None = None


def resolve_ref(ref: str) -> LinkTarget | None:
    """Resolve *ref* to a followable target, or ``None`` if it dead-ends.

    ``ref`` is a normalized ref string: a typed artifact reference
    (``bead:sase-uk.5``), or a plain filesystem path. Never called for URL
    spans — the press table copies those directly (D6) without resolving.
    """
    stripped = ref.strip()
    if not stripped:
        return None
    try:
        parse_artifact_ref(stripped)
    except (ImportError, RuntimeError, ValueError):
        return _resolve_file_path_target(stripped)
    return _resolve_artifact_ref_target(stripped)


def link_target_for_artifact_entry_target(
    ref: str,
    target: ArtifactEntryTarget,
) -> LinkTarget | None:
    """Resolve an already-indexed ACE artifact target into a pager landing.

    The ACE link rail's ``LinkIndex`` has already paid the graph lookup cost
    and synthesized the destination ``ArtifactEntryTarget``.  This adapter
    skips the artifact-reference discovery path for common concrete panes and
    falls back to the canonical ref resolver only when the target has no direct
    pager document shape.
    """

    if target.pane_id == "files" and target.parts:
        return _resolve_file_path_target(str(target.parts[-1]))
    if target.pane_id == "beads" and target.parts:
        return _bead_link_target(f"bead:{target.parts[-1]}")
    canonical_ref = _ref_for_artifact_entry_target(target) or ref
    return _resolve_artifact_ref_target(canonical_ref)


def _resolve_artifact_ref_target(ref: str) -> LinkTarget | None:
    try:
        result = resolve_cli_reference(ref)
    except (ImportError, RuntimeError, ValueError):
        return None
    if result.resolution.status not in _RESOLVED_STATUSES:
        return None

    kind_type = result.parsed.kind_type
    if kind_type == "bead":
        return _bead_link_target(result.canonical_reference)
    if kind_type in {"stitch", "commit"}:
        return _card_link_target(result, path=result.resolution.resolved_path)

    try:
        path = resolved_file_path(result)
    except (ImportError, OSError, RuntimeError, ValueError):
        path = result.resolution.resolved_path
    if path is None:
        return _card_link_target(result, path=None)
    if path.is_dir():
        return _directory_link_target(path)

    line = _fragment_line(result.parsed.fragment)
    mode = artifact_file_view_mode(
        path,
        kind=(result.file.kind if result.file is not None else result.parsed.kind),
    )
    if mode in _MEDIA_MODES:
        return LinkTarget(
            kind=LinkTargetKind.MEDIA,
            media_specs=(ArtifactFileViewSpec(path, kind=mode),),
            edit_path=path,
            edit_line=line,
        )
    if _is_probably_text(path):
        return _file_link_target(path, requested_line=line)
    return _card_link_target(result, path=path)


def _resolve_file_path_target(text: str) -> LinkTarget | None:
    path = Path(text).expanduser()
    path = (
        path.resolve(strict=False)
        if path.is_absolute()
        else (Path.cwd() / path).resolve(strict=False)
    )
    if not path.exists():
        return None
    if path.is_dir():
        return _directory_link_target(path)

    mode = artifact_file_view_mode(path)
    if mode in _MEDIA_MODES:
        return LinkTarget(
            kind=LinkTargetKind.MEDIA,
            media_specs=(ArtifactFileViewSpec(path, kind=mode),),
            edit_path=path,
        )
    if _is_probably_text(path):
        return _file_link_target(path, requested_line=None)
    return LinkTarget(
        kind=LinkTargetKind.DOCUMENT,
        document=_binary_card_document(str(path), path=path, mime=_guess_mime(path)),
        edit_path=path,
    )


def _bead_link_target(canonical_ref: str) -> LinkTarget | None:
    bead_id = canonical_ref.split(":", 1)[-1]
    from sase.agent.names._registry import name_registry_load_session
    from sase.bead.cli_common import get_read_view
    from sase.bead.cli_detail import (
        artifact_reference_context,
        design_paths_are_relative,
        plan_reference_roots,
        resolve_bead_creator_url,
        resolve_bead_page_url,
    )
    from sase.bead.cli_detail_style import DetailStyle
    from sase.bead.cli_show_batch import (
        build_show_batch_document,
        enrich_with_artifact_link_neighborhood,
        resolve_show_batch,
    )

    try:
        with name_registry_load_session(), get_read_view() as view:
            batch = resolve_show_batch(
                view,
                [bead_id],
                format_name="full",
                include_links=True,
                # `sase bead show`'s own enricher exits the process when the
                # link store cannot be read; a keypress handler cannot.
                detail_enricher=enrich_with_artifact_link_neighborhood,
            )
            if batch.failures or not batch.entries:
                return None
            return LinkTarget(
                kind=LinkTargetKind.DOCUMENT,
                document=build_show_batch_document(
                    batch,
                    style=DetailStyle.RICH,
                    wrap=None,
                    relativize_design=design_paths_are_relative(),
                    plan_roots=plan_reference_roots(),
                    reference_context_factory=artifact_reference_context,
                    creator_url_for=resolve_bead_creator_url,
                    page_url_for=resolve_bead_page_url,
                ),
            )
    except Exception:
        log.exception("pager: could not resolve bead ref %r", canonical_ref)
        return None


def _directory_link_target(path: Path) -> LinkTarget | None:
    try:
        entries = sorted(path.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return None
    lines = [f"{entry}{'/' if entry.is_dir() else ''}" for entry in entries]
    body = "\n".join(lines) + "\n" if lines else "(empty directory)\n"
    document = PagerDocument(
        sections=(
            PagerSection(
                identity=f"file:{path}",
                title=str(path),
                kind="file",
                body=body,
                subject_ref=f"file:{path}",
            ),
        ),
        title=f"{len(entries)} entries · {path.name or str(path)}",
        origin=PagerOrigin.FILE,
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def _file_link_target(path: Path, *, requested_line: int | None) -> LinkTarget:
    section = path_section(path)
    document = PagerDocument(
        sections=(section,), title=path.name, origin=PagerOrigin.FILE
    )
    return LinkTarget(
        kind=LinkTargetKind.DOCUMENT,
        document=document,
        scroll_line=requested_line,
        edit_path=path,
        edit_line=requested_line,
    )


def _card_link_target(
    result: ResolvedArtifactReference,
    *,
    path: Path | None,
) -> LinkTarget:
    kind = result.file.kind if result.file is not None else result.parsed.kind
    mime = result.file.mime_type if result.file is not None else None
    document = _binary_card_document(
        result.canonical_reference,
        path=path,
        mime=mime,
        kind=kind,
        status=result.resolution.status,
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def _binary_card_document(
    title: str,
    *,
    path: Path | None,
    mime: str | None,
    kind: str | None = None,
    status: str | None = None,
) -> PagerDocument:
    lines = []
    if kind is not None:
        lines.append(f"kind: {kind}")
    lines.append(f"reference: {title}")
    if status is not None:
        lines.append(f"status: {status}")
    lines.append(f"mime_type: {mime or '-'}")
    lines.append(f"path: {path if path is not None else '-'}")
    body = "\n".join(lines) + "\n"
    return PagerDocument(
        sections=(PagerSection(identity=title, title=title, kind="file", body=body),),
        title=title,
        origin=PagerOrigin.FILE,
    )


def _fragment_line(fragment: ArtifactRefFragment | None) -> int | None:
    if fragment is not None and fragment.type == "lines" and fragment.start is not None:
        return fragment.start
    return None


def _is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return True
    mime = _guess_mime(path)
    if mime is None:
        return path.suffix.lower() in {".py", ".sh"}
    return mime.startswith(_TEXT_MIME_PREFIXES) or mime in _TEXT_MIME_TYPES


def _guess_mime(path: Path) -> str | None:
    return mimetypes.guess_type(str(path))[0]


def _ref_for_artifact_entry_target(target: ArtifactEntryTarget) -> str | None:
    try:
        from sase.ace.tui.relations.link_subject import ref_for_target

        return ref_for_target(target)
    except Exception:
        log.exception("pager: could not convert artifact target %r to ref", target)
        return None


def copy_text_for_target(ref: str, kind: str) -> str:
    """Return the text ``y`` should copy for a scanned/attached target.

    A file path copies its resolved absolute path; every other kind copies
    its ref text verbatim, matching D8's "canonical ref or path" wording.
    """
    if kind == LinkSpanKind.FILE_PATH.value:
        path = Path(ref).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return str(path.resolve(strict=False))
    return ref


__all__ = [
    "LinkTarget",
    "LinkTargetKind",
    "copy_text_for_target",
    "link_target_for_artifact_entry_target",
    "resolve_ref",
]

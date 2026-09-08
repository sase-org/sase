"""Resolve a followed ref into a target the pager can land on.

D6's single narrow interface (``resolve_ref``), backed by the same CLI
reference resolution ``sase artifact read``/``sase bead show`` already use.
This module does real I/O — filesystem stats, bead-store reads, VCS
materialization — so it must never run on the UI thread. ``PagerScreen``
dispatches it through ``asyncio.to_thread`` inside a pump-free task with a
generation check (see ``screen.py``); the resolution itself stays synchronous
and side-effect free here so it is trivially testable without booting Textual.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import re
import select
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

from sase.ace.tui.graphics import ArtifactFileViewSpec, artifact_file_view_mode
from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    resolve_cli_reference,
    resolved_file_path,
)
from sase.artifact_ref_context import artifact_ref_context
from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefFragment,
    ArtifactRefTargetResolution,
)
from sase.artifact_ref_operations import parse_artifact_ref
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.source_language_facade import logical_source_filename
from sase.pager.adapters import path_section
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import (
    LinkAnchor,
    LinkResolutionContext,
    default_link_context,
)
from sase.pager.known_kinds import known_kinds_from_link_context
from sase.pager.link_scan import LinkSpanKind
from sase.pager.landings import (
    ambiguous_source_resolution,
    binary_card_document,
    card_link_target,
    commit_link_target,
)
from sase.pager.owner import (
    artifact_context_for_link_context,
    document_owner_from_path,
    inherit_owner_context,
)
from sase.pager.source_resolve import (
    lookup_owned_source_path,
    owned_source_is_retryable,
    owned_source_is_success,
    owned_source_unresolved_message,
)
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind
from sase.pager.syntax_policy import (
    artifact_syntax_category,
    is_openable_text_path,
)

log = logging.getLogger(__name__)

_RESOLVED_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})
_MEDIA_MODES = frozenset({"image", "video", "pdf"})

_LINE_COL_SUFFIX_RE = re.compile(r"(.+):(\d+):(\d+)$")
_LINE_SUFFIX_RE = re.compile(r"(.+):(\d+)$")
_TRAILING_LINE_DIGITS_RE = re.compile(r":\d+$")
_LINE_FRAGMENT_RE = re.compile(r"L(\d+)(?:-L?\d+)?", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})
_NUMBERED_CHECKOUT_RE = re.compile(r"^.+_\d+$")
_DIFF_PREFIXES = ("a/", "b/")
_GIT_LS_FILES_TIMEOUT_SECONDS = 2.0
_GIT_LS_FILES_MAX_BYTES = 1_048_576

_GitLsFilesCache = dict[Path, tuple[str, ...] | None]
_PathConsider = Callable[[Path], Path | None]


def resolve_ref(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    """Resolve *ref* to a followable target, or ``None`` if it dead-ends.

    ``ref`` is a normalized ref string: a typed artifact reference
    (``bead:sase-uk.5``), or a plain filesystem path. Never called for URL
    spans — the press table copies those directly (D6) without resolving.
    ``context`` is computed lazily for file paths; typed refs with ``None``
    or empty anchors keep today's ``resolve_cli_reference(ref)`` call.
    """
    return resolve_link(ref, context=context).target


def resolve_link(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    """Resolve *ref* and return any file-path dead-end diagnostics.

    This is the pager's one background attempt. Callers that only need the
    target should use :func:`resolve_ref`.
    """
    stripped = ref.strip()
    if not stripped:
        return LinkResolution()
    try:
        parse_artifact_ref(stripped)
    except (ImportError, RuntimeError, ValueError):
        return _resolve_file_path_link(stripped, context=context)
    return _resolve_artifact_ref_link(stripped, context=context)


def link_target_for_artifact_entry_target(
    ref: str,
    target: ArtifactEntryTarget,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    """Resolve an already-indexed ACE artifact target into a pager landing.

    The ACE link rail's ``LinkIndex`` has already paid the graph lookup cost
    and synthesized the destination ``ArtifactEntryTarget``.  This adapter
    skips the artifact-reference discovery path for common concrete panes and
    falls back to the canonical ref resolver only when the target has no direct
    pager document shape. *context* is retained on the fast path so materialized
    reports do not land as contextless temporary files.
    """

    if target.pane_id == "files" and target.parts:
        return _resolve_file_path_target(str(target.parts[-1]), context=context)
    if target.pane_id == "beads" and target.parts:
        return _bead_link_target(f"bead:{target.parts[-1]}")
    canonical_ref = _ref_for_artifact_entry_target(target) or ref
    return _resolve_artifact_ref_target(canonical_ref, context=context)


def _resolve_artifact_ref_target(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    return _resolve_artifact_ref_link(ref, context=context).target


def _resolve_artifact_ref_link(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    if context is None or not context.anchors:
        return _resolve_artifact_result(
            ref,
            artifact_context=None,
            link_context=context,
        )
    last = LinkResolution()
    for anchor in context.anchors:
        artifact_context = _artifact_ref_context_for_anchor(anchor)
        if artifact_context is None:
            continue
        resolution = _resolve_artifact_result(
            ref,
            artifact_context=artifact_context,
            link_context=context,
        )
        if resolution.target is not None:
            return resolution
        last = resolution
    return last


def _artifact_ref_context_for_anchor(anchor: LinkAnchor) -> ArtifactRefContext | None:
    try:
        return artifact_ref_context(anchor.directory, anchor.workspace_num or 1)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return None


def _resolve_artifact_result(
    ref: str,
    *,
    artifact_context: ArtifactRefContext | None,
    link_context: LinkResolutionContext | None,
) -> LinkResolution:
    try:
        result = (
            resolve_cli_reference(ref)
            if artifact_context is None
            else resolve_cli_reference(ref, context=artifact_context)
        )
    except (ImportError, RuntimeError, ValueError) as exc:
        return LinkResolution(unresolved_message=f"{ref} could not be resolved - {exc}")
    if result.resolution.status not in _RESOLVED_STATUSES:
        diagnostic = (
            getattr(result.resolution, "diagnostic", None)
            or f"{ref} could not be resolved."
        )
        retryable = (
            result.resolution.status
            in {
                "missing",
                "unknown_repo",
            }
            and "ambiguous" not in diagnostic.lower()
        )
        return LinkResolution(unresolved_message=diagnostic, retryable=retryable)

    kind_type = result.parsed.kind_type
    if kind_type == "bead":
        return LinkResolution(target=_bead_link_target(result.canonical_reference))
    if kind_type in {"stitch", "commit"}:
        return LinkResolution(target=commit_link_target(result, context=link_context))

    try:
        path = resolved_file_path(result)
    except (ImportError, OSError, RuntimeError, ValueError):
        path = result.resolution.resolved_path
    if path is None:
        return LinkResolution(
            target=card_link_target(result, path=None, context=link_context)
        )
    if path.is_dir():
        return LinkResolution(target=_directory_link_target(path, context=link_context))

    line = _fragment_line(result.parsed.fragment)
    mode = artifact_file_view_mode(
        path,
        kind=(result.file.kind if result.file is not None else result.parsed.kind),
    )
    if mode in _MEDIA_MODES:
        return LinkResolution(
            target=LinkTarget(
                kind=LinkTargetKind.MEDIA,
                media_specs=(ArtifactFileViewSpec(path, kind=mode),),
                edit_path=path,
                edit_line=line,
            )
        )
    logical = _artifact_logical_filename(result, path)
    file_kind = result.file.kind if result.file is not None else result.parsed.kind
    if _is_probably_text(path, logical_filename=logical):
        return LinkResolution(
            target=_file_link_target(
                path,
                requested_line=line,
                context=link_context,
                logical_filename=logical,
                category=artifact_syntax_category(kind_type=kind_type, kind=file_kind),
                subject_ref=result.canonical_reference,
            )
        )
    return LinkResolution(
        target=card_link_target(result, path=path, context=link_context)
    )


def _resolve_file_path_target(
    text: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    return _resolve_file_path_link(text, context=context).target


def _resolve_file_path_link(
    text: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    resolved_context = _file_path_context(context)
    owned = _owned_file_path_resolution(text, context=resolved_context)
    if owned is not None:
        return owned
    found, line, column, fragment, locations = _search_existing_path(
        text, context=resolved_context
    )
    if found is None:
        return LinkResolution(
            unresolved_message=f"{text} not found (searched {locations} locations)",
        )
    return _link_resolution_for_existing_path(
        found,
        requested_line=line,
        requested_column=column,
        fragment=fragment,
        context=resolved_context,
    )


def _owned_file_path_resolution(
    text: str,
    *,
    context: LinkResolutionContext,
) -> LinkResolution | None:
    if context.owner is None:
        return None
    last: ArtifactRefTargetResolution | None = None
    last_path = text
    for path_text, line, column, fragment in _path_candidates(text):
        owned = lookup_owned_source_path(path_text, context=context)
        if owned is None:
            continue
        last = owned
        last_path = path_text
        if owned_source_is_success(owned) and owned.resolved_path is not None:
            return _link_resolution_for_existing_path(
                owned.resolved_path,
                requested_line=line,
                requested_column=column,
                fragment=fragment,
                context=context,
            )
        if owned.status == "ambiguous" or owned.failure_category == "ambiguous":
            return ambiguous_source_resolution(path_text, owned, context)
    if last is None:
        return None
    return LinkResolution(
        unresolved_message=owned_source_unresolved_message(last_path, last),
        retryable=owned_source_is_retryable(last),
    )


def _link_target_for_existing_path(
    path: Path,
    *,
    requested_line: int | None,
    requested_column: int | None = None,
    context: LinkResolutionContext,
) -> LinkTarget | None:
    if path.is_dir():
        return _directory_link_target(path, context=context)

    mode = artifact_file_view_mode(path)
    if mode in _MEDIA_MODES:
        return LinkTarget(
            kind=LinkTargetKind.MEDIA,
            media_specs=(ArtifactFileViewSpec(path, kind=mode),),
            edit_path=path,
            edit_line=requested_line,
            edit_column=requested_column,
        )
    if _is_probably_text(path):
        return _file_link_target(
            path,
            requested_line=requested_line,
            requested_column=requested_column,
            context=context,
        )
    return LinkTarget(
        kind=LinkTargetKind.DOCUMENT,
        document=binary_card_document(
            str(path),
            path=path,
            mime=_guess_mime(path),
            context=context,
        ),
        edit_path=path,
        edit_line=requested_line,
        edit_column=requested_column,
    )


def _bead_link_target(canonical_ref: str) -> LinkTarget | None:
    bead_id = canonical_ref.split(":", 1)[-1]
    from sase.agent.names._registry import name_registry_load_session
    from sase.bead.cli_common import get_read_view
    from sase.bead.cli_detail_style import DetailStyle
    from sase.bead.cli_show_router import ShowStoreRouter
    from sase.bead.cli_show_batch import (
        build_show_batch_document,
        default_show_render_context_resolver,
        enrich_with_artifact_link_neighborhood,
        resolve_show_batch,
    )

    try:
        with name_registry_load_session(), get_read_view() as view:
            with ShowStoreRouter(view) as router:
                batch = resolve_show_batch(
                    view,
                    [bead_id],
                    format_name="full",
                    include_links=True,
                    # `sase bead show`'s own enricher exits the process when the
                    # link store cannot be read; a keypress handler cannot.
                    detail_enricher=enrich_with_artifact_link_neighborhood,
                    router=router,
                )
                if batch.failures or not batch.entries:
                    return None
                return LinkTarget(
                    kind=LinkTargetKind.DOCUMENT,
                    document=build_show_batch_document(
                        batch,
                        style=DetailStyle.RICH,
                        wrap=None,
                        render_context_for=default_show_render_context_resolver(),
                    ),
                )
    except Exception:
        log.exception("pager: could not resolve bead ref %r", canonical_ref)
        return None


def _directory_link_target(
    path: Path,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
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
                owner=document_owner_from_path(path, source_reference=f"file:{path}"),
            ),
        ),
        title=f"{len(entries)} entries · {path.name or str(path)}",
        origin=PagerOrigin.FILE,
        link_context=inherit_owner_context(path, context),
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def _file_link_target(
    path: Path,
    *,
    requested_line: int | None,
    requested_column: int | None = None,
    context: LinkResolutionContext | None = None,
    logical_filename: str | None = None,
    category: str = "raw_file",
    subject_ref: str | None = None,
) -> LinkTarget:
    section = path_section(
        path,
        logical_filename=logical_filename,
        category=category,
        subject_ref=subject_ref,
        known_kinds=known_kinds_from_link_context(context),
    )
    document = PagerDocument(
        sections=(section,),
        title=path.name,
        origin=PagerOrigin.FILE,
        link_context=inherit_owner_context(path, context),
    )
    return LinkTarget(
        kind=LinkTargetKind.DOCUMENT,
        document=document,
        scroll_line=requested_line,
        edit_path=path,
        edit_line=requested_line,
        edit_column=requested_column,
    )


def _fragment_line(fragment: ArtifactRefFragment | None) -> int | None:
    if fragment is not None and fragment.type == "lines" and fragment.start is not None:
        return fragment.start
    return None


def _is_probably_text(
    path: Path,
    *,
    logical_filename: str | None = None,
) -> bool:
    return is_openable_text_path(
        path,
        logical_filename=logical_filename,
        mime=_guess_mime(path),
    )


def _artifact_logical_filename(
    result: ResolvedArtifactReference,
    path: Path | None,
) -> str | None:
    artifact_file = result.file
    return logical_source_filename(
        source_path=None if artifact_file is None else artifact_file.source_path,
        vcs_relpath=None if artifact_file is None else artifact_file.vcs_relpath,
        resolved_path=None if path is None else str(path),
    )


def _guess_mime(path: Path) -> str | None:
    return mimetypes.guess_type(str(path))[0]


def _ref_for_artifact_entry_target(target: ArtifactEntryTarget) -> str | None:
    try:
        from sase.ace.tui.relations.link_subject import ref_for_target

        return ref_for_target(target)
    except Exception:
        log.exception("pager: could not convert artifact target %r to ref", target)
        return None


def copy_text_for_target(
    ref: str,
    kind: str,
    *,
    context: LinkResolutionContext | None = None,
) -> str:
    """Return the text ``y`` should copy for a scanned/attached target.

    A file path copies its first existing resolution. Unavailable paths
    copy the original logical token rather than inventing a cwd-joined
    path. Every other kind copies its ref text verbatim.
    """
    if kind == LinkSpanKind.FILE_PATH.value:
        resolved_context = _file_path_context(context)
        owned = _owned_file_path_resolution(ref, context=resolved_context)
        if owned is not None and owned.target is not None:
            if owned.target.edit_path is not None:
                return str(owned.target.edit_path)
        found, _line, _column, fragment, _locations = _search_existing_path(
            ref, context=resolved_context
        )
        if found is not None:
            _fragment_line, fragment_message = _fragment_target_line(found, fragment)
            if fragment_message is not None:
                return ref
            return str(found)
        return ref
    return ref


def _file_path_context(
    context: LinkResolutionContext | None,
) -> LinkResolutionContext:
    if context is not None:
        return context
    return default_link_context()


def _search_existing_path(
    text: str,
    *,
    context: LinkResolutionContext,
    cache: _GitLsFilesCache | None = None,
) -> tuple[Path | None, int | None, int | None, str | None, int]:
    """Return ``(path, line, column, fragment, locations_probed)`` for the first hit."""
    git_cache: _GitLsFilesCache = {} if cache is None else cache
    probed: list[Path] = []
    seen: set[Path] = set()

    def consider(path: Path) -> Path | None:
        resolved = _resolved_path(path)
        if resolved not in seen:
            seen.add(resolved)
            probed.append(resolved)
        if resolved.exists():
            return resolved
        return None

    candidates = _path_candidates(text)
    for path_text, line, column, fragment in candidates:
        found = _probe_direct(path_text, context, consider)
        if found is not None:
            return found, line, column, fragment, len(probed)
    for path_text, line, column, fragment in candidates:
        needle = _suffix_needle(path_text, context)
        if needle is None:
            continue
        found = _unique_suffix_hit(needle, context, git_cache, consider)
        if found is not None:
            return found, line, column, fragment, len(probed)
    return None, None, None, None, len(probed)


def _probe_direct(
    path_text: str,
    context: LinkResolutionContext,
    consider: _PathConsider,
) -> Path | None:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        found = consider(path)
        if found is not None:
            return found
        remainder = _stale_absolute_remainder(path, context)
        if remainder is None:
            return None
        for base in context.base_dirs:
            found = consider(base / remainder)
            if found is not None:
                return found
        return None
    for base in context.base_dirs:
        found = consider(base / path)
        if found is not None:
            return found
    return None


def _unique_suffix_hit(
    needle: str,
    context: LinkResolutionContext,
    cache: _GitLsFilesCache,
    consider: _PathConsider,
) -> Path | None:
    hits: list[Path] = []
    seen: set[Path] = set()
    for anchor in context.anchors:
        for tracked in _cached_git_ls_files(anchor.directory, cache):
            if not _is_suffix_match(tracked, needle):
                continue
            resolved = _resolved_path(anchor.directory / tracked)
            if resolved in seen:
                continue
            seen.add(resolved)
            hits.append(resolved)
    if len(hits) != 1:
        return None
    return consider(hits[0])


def _path_candidates(
    text: str,
) -> tuple[tuple[str, int | None, int | None, str | None], ...]:
    seen: set[str] = set()
    candidates: list[tuple[str, int | None, int | None, str | None]] = []
    for variant in _candidate_texts(text):
        path_text, line, column, fragment = _split_target_suffix(variant)
        key = f"{path_text}#{fragment}" if fragment is not None else path_text
        if not path_text or key in seen:
            continue
        seen.add(key)
        candidates.append((path_text, line, column, fragment))
    return tuple(candidates)


def _candidate_texts(text: str) -> tuple[str, ...]:
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    add(text)
    add(text.rstrip("."))
    for variant in tuple(variants):
        for prefix in _DIFF_PREFIXES:
            if variant.startswith(prefix) and len(variant) > len(prefix):
                add(variant[len(prefix) :])
                break
    return tuple(variants)


def _split_target_suffix(
    text: str,
) -> tuple[str, int | None, int | None, str | None]:
    path_text, fragment = _split_hash_fragment(text)
    path_text, line, column = _split_line_suffix(path_text)
    return path_text, line, column, fragment


def _split_hash_fragment(text: str) -> tuple[str, str | None]:
    if "#" not in text:
        return text, None
    path_text, fragment = text.split("#", 1)
    return path_text, fragment


def _split_line_suffix(text: str) -> tuple[str, int | None, int | None]:
    match = _LINE_COL_SUFFIX_RE.fullmatch(text)
    if match is not None:
        path_text = match.group(1)
        if not _TRAILING_LINE_DIGITS_RE.search(path_text):
            return path_text, int(match.group(2)), int(match.group(3))
    match = _LINE_SUFFIX_RE.fullmatch(text)
    if match is not None:
        path_text = match.group(1)
        if not _TRAILING_LINE_DIGITS_RE.search(path_text):
            return path_text, int(match.group(2)), None
    return text, None, None


def _link_resolution_for_existing_path(
    path: Path,
    *,
    requested_line: int | None,
    requested_column: int | None,
    fragment: str | None,
    context: LinkResolutionContext,
) -> LinkResolution:
    fragment_line, fragment_message = _fragment_target_line(path, fragment)
    if fragment_message is not None:
        return LinkResolution(unresolved_message=fragment_message)
    return LinkResolution(
        target=_link_target_for_existing_path(
            path,
            requested_line=fragment_line
            if fragment_line is not None
            else requested_line,
            requested_column=requested_column,
            context=context,
        )
    )


def _fragment_target_line(
    path: Path,
    fragment: str | None,
) -> tuple[int | None, str | None]:
    if fragment is None:
        return None, None
    decoded = unquote(fragment)
    if not decoded:
        return None, None
    line_match = _LINE_FRAGMENT_RE.fullmatch(decoded)
    if line_match is not None:
        return int(line_match.group(1)), None
    if decoded[:1].lower() == "l" and any(char.isdigit() for char in decoded):
        return None, f"fragment #{decoded} is not a supported line fragment for {path}"
    if not _is_markdown_path(path):
        return None, f"fragment #{decoded} is not supported for {path}"
    line = _heading_fragment_line(path, decoded)
    if line is None:
        return None, f"fragment #{decoded} was not found in {path}"
    return line, None


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_SUFFIXES


def _heading_fragment_line(path: Path, fragment: str) -> int | None:
    wanted = _heading_slug(fragment)
    if not wanted:
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    seen: dict[str, int] = {}
    for line_number, line in enumerate(lines, start=1):
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        base = _heading_slug(match.group(1))
        if not base:
            continue
        ordinal = seen.get(base, 0)
        seen[base] = ordinal + 1
        slug = base if ordinal == 0 else f"{base}-{ordinal}"
        if slug == wanted:
            return line_number
    return None


def _heading_slug(text: str) -> str:
    output: list[str] = []
    last_dash = False
    for character in text.strip().lower():
        if character.isspace() or character == "-":
            if output and not last_dash:
                output.append("-")
                last_dash = True
            continue
        if character.isalnum() or character == "_":
            output.append(character)
            last_dash = False
    while output and output[-1] == "-":
        output.pop()
    return "".join(output)


def _stale_absolute_remainder(
    path: Path, context: LinkResolutionContext
) -> Path | None:
    resolved = _resolved_path(path)
    anchor_dirs = {_resolved_path(base) for base in context.base_dirs}
    for prefix in (resolved, *resolved.parents):
        numbered = _NUMBERED_CHECKOUT_RE.fullmatch(prefix.name) is not None
        if prefix not in anchor_dirs and not numbered:
            continue
        try:
            return resolved.relative_to(prefix)
        except ValueError:
            continue
    return None


def _suffix_needle(path_text: str, context: LinkResolutionContext) -> str | None:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        remainder = _stale_absolute_remainder(path, context)
        if remainder is None:
            return None
        posix = remainder.as_posix()
    else:
        posix = path.as_posix().lstrip("./")
    if posix in {"", "."} or len(Path(posix).parts) < 2:
        return None
    return posix


def _is_suffix_match(tracked: str, needle: str) -> bool:
    tracked_posix = tracked.replace("\\", "/").lstrip("./")
    needle_posix = needle.replace("\\", "/").lstrip("./")
    if not needle_posix:
        return False
    return tracked_posix == needle_posix or tracked_posix.endswith("/" + needle_posix)


def _cached_git_ls_files(directory: Path, cache: _GitLsFilesCache) -> tuple[str, ...]:
    key = _resolved_path(directory)
    if key not in cache:
        cache[key] = _git_ls_files(key)
    files = cache[key]
    return files if files else ()


def _git_ls_files(directory: Path) -> tuple[str, ...] | None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(directory), "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        captured = _capture_bounded_process_output(
            proc,
            max_bytes=_GIT_LS_FILES_MAX_BYTES,
            timeout_seconds=_GIT_LS_FILES_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        if proc is not None:
            _kill_and_reap_process(proc)
        return None
    if captured is None:
        return None
    return tuple(
        chunk.decode("utf-8", "replace") for chunk in captured.split(b"\0") if chunk
    )


def _capture_bounded_process_output(
    proc: subprocess.Popen[bytes],
    *,
    max_bytes: int,
    timeout_seconds: float,
) -> bytes | None:
    """Read *proc* stdout up to *max_bytes*, then wait or kill.

    Output at the limit is kept. One extra byte is a miss: the child is
    killed and the buffer is discarded rather than returned as a partial
    candidate list. Timeout and overflow always reap the child.
    """
    stdout = proc.stdout
    if stdout is None:
        _kill_and_reap_process(proc)
        return None
    deadline = time.monotonic() + timeout_seconds
    chunks: list[bytes] = []
    total = 0
    overflow = False
    timed_out = False
    fd = stdout.fileno()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                timed_out = True
                break
            try:
                chunk = os.read(fd, min(65536, max_bytes - total + 1))
            except OSError:
                break
            if not chunk:
                break
            if total + len(chunk) > max_bytes:
                overflow = True
                break
            chunks.append(chunk)
            total += len(chunk)
    except (OSError, ValueError):
        _kill_and_reap_process(proc)
        return None
    if overflow or timed_out:
        _kill_and_reap_process(proc)
        return None
    returncode = proc.poll()
    if returncode is None:
        remaining = deadline - time.monotonic()
        try:
            returncode = proc.wait(timeout=max(remaining, 0.0))
        except subprocess.TimeoutExpired:
            _kill_and_reap_process(proc)
            return None
    if returncode != 0:
        return None
    return b"".join(chunks)


def _kill_and_reap_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.kill()
    stdout = proc.stdout
    if stdout is not None:
        try:
            fd = stdout.fileno()
        except (OSError, ValueError):
            fd = None
        if fd is not None:
            try:
                while True:
                    ready, _, _ = select.select([fd], [], [], 0)
                    if not ready:
                        break
                    if not os.read(fd, 65536):
                        break
            except (OSError, ValueError):
                pass
        try:
            stdout.close()
        except OSError:
            pass
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _resolved_path(path: Path) -> Path:
    expanded = path.expanduser()
    try:
        return expanded.resolve(strict=False)
    except OSError:
        return expanded


__all__ = [
    "LinkResolution",
    "LinkTarget",
    "LinkTargetKind",
    "copy_text_for_target",
    "link_target_for_artifact_entry_target",
    "resolve_link",
    "resolve_ref",
]

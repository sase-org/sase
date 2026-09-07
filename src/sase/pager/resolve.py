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
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sase.ace.tui.graphics import ArtifactFileViewSpec, artifact_file_view_mode
from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    resolve_cli_reference,
    resolved_file_path,
)
from sase.artifact_ref_context import artifact_ref_context
from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefFragment
from sase.artifact_ref_operations import parse_artifact_ref
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager.adapters import path_section
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import (
    LinkAnchor,
    LinkResolutionContext,
    default_link_context,
    inherited_link_context,
)
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
_LINE_COL_SUFFIX_RE = re.compile(r"(.+):(\d+):(\d+)$")
_LINE_SUFFIX_RE = re.compile(r"(.+):(\d+)$")
_TRAILING_LINE_DIGITS_RE = re.compile(r":\d+$")
_NUMBERED_CHECKOUT_RE = re.compile(r"^.+_\d+$")
_DIFF_PREFIXES = ("a/", "b/")
_GIT_LS_FILES_TIMEOUT_SECONDS = 2.0
_GIT_LS_FILES_MAX_BYTES = 1_048_576

_GitLsFilesCache = dict[Path, tuple[str, ...] | None]
_PathConsider = Callable[[Path], Path | None]


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


@dataclass(frozen=True, slots=True)
class LinkResolution:
    """One background resolution attempt and any UI-ready dead-end copy.

    The pager apply path must consume this object as-is: it must not search,
    stat, or talk to Git again to rebuild a toast. ``resolve_ref`` is the
    convenience wrapper that returns only ``target``.
    """

    target: LinkTarget | None = None
    unresolved_message: str | None = None


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
    return LinkResolution(
        target=_resolve_artifact_ref_target(stripped, context=context)
    )


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


def _resolve_artifact_ref_target(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    if context is None or not context.anchors:
        return _resolve_artifact_result(
            ref,
            artifact_context=None,
            link_context=context,
        )
    for anchor in context.anchors:
        artifact_context = _artifact_ref_context_for_anchor(anchor)
        if artifact_context is None:
            continue
        target = _resolve_artifact_result(
            ref,
            artifact_context=artifact_context,
            link_context=context,
        )
        if target is not None:
            return target
    return None


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
) -> LinkTarget | None:
    try:
        result = (
            resolve_cli_reference(ref)
            if artifact_context is None
            else resolve_cli_reference(ref, context=artifact_context)
        )
    except (ImportError, RuntimeError, ValueError):
        return None
    if result.resolution.status not in _RESOLVED_STATUSES:
        return None

    kind_type = result.parsed.kind_type
    if kind_type == "bead":
        return _bead_link_target(result.canonical_reference)
    if kind_type in {"stitch", "commit"}:
        return _card_link_target(
            result,
            path=result.resolution.resolved_path,
            context=link_context,
        )

    try:
        path = resolved_file_path(result)
    except (ImportError, OSError, RuntimeError, ValueError):
        path = result.resolution.resolved_path
    if path is None:
        return _card_link_target(result, path=None, context=link_context)
    if path.is_dir():
        return _directory_link_target(path, context=link_context)

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
        return _file_link_target(path, requested_line=line, context=link_context)
    return _card_link_target(result, path=path, context=link_context)


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
    found, line, locations = _search_existing_path(text, context=resolved_context)
    if found is None:
        return LinkResolution(
            unresolved_message=f"{text} not found (searched {locations} locations)",
        )
    return LinkResolution(
        target=_link_target_for_existing_path(
            found,
            requested_line=line,
            context=resolved_context,
        )
    )


def _link_target_for_existing_path(
    path: Path,
    *,
    requested_line: int | None,
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
        )
    if _is_probably_text(path):
        return _file_link_target(
            path,
            requested_line=requested_line,
            context=context,
        )
    return LinkTarget(
        kind=LinkTargetKind.DOCUMENT,
        document=_binary_card_document(
            str(path),
            path=path,
            mime=_guess_mime(path),
            context=context,
        ),
        edit_path=path,
        edit_line=requested_line,
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
            ),
        ),
        title=f"{len(entries)} entries · {path.name or str(path)}",
        origin=PagerOrigin.FILE,
        link_context=_inherited_context(path, context),
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def _file_link_target(
    path: Path,
    *,
    requested_line: int | None,
    context: LinkResolutionContext | None = None,
) -> LinkTarget:
    section = path_section(path)
    document = PagerDocument(
        sections=(section,),
        title=path.name,
        origin=PagerOrigin.FILE,
        link_context=_inherited_context(path, context),
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
    context: LinkResolutionContext | None = None,
) -> LinkTarget:
    kind = result.file.kind if result.file is not None else result.parsed.kind
    mime = result.file.mime_type if result.file is not None else None
    document = _binary_card_document(
        result.canonical_reference,
        path=path,
        mime=mime,
        kind=kind,
        status=result.resolution.status,
        context=context,
    )
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document, edit_path=path)


def _binary_card_document(
    title: str,
    *,
    path: Path | None,
    mime: str | None,
    kind: str | None = None,
    status: str | None = None,
    context: LinkResolutionContext | None = None,
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
        link_context=(
            _inherited_context(path, context) if path is not None else context
        ),
    )


def _inherited_context(
    path: Path,
    context: LinkResolutionContext | None,
) -> LinkResolutionContext | None:
    if context is None:
        return None
    return inherited_link_context(path, context)


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


def copy_text_for_target(
    ref: str,
    kind: str,
    *,
    context: LinkResolutionContext | None = None,
) -> str:
    """Return the text ``y`` should copy for a scanned/attached target.

    A file path copies its first existing resolution; when nothing exists
    it falls back to today's cwd-joined absolute string. Every other kind
    copies its ref text verbatim, matching D8's "canonical ref or path"
    wording.
    """
    if kind == LinkSpanKind.FILE_PATH.value:
        found, _line, _locations = _search_existing_path(
            ref, context=_file_path_context(context)
        )
        if found is not None:
            return str(found)
        path = Path(ref).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return str(path.resolve(strict=False))
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
) -> tuple[Path | None, int | None, int]:
    """Return ``(path, line, locations_probed)`` for the first existing hit."""
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
    for path_text, line in candidates:
        found = _probe_direct(path_text, context, consider)
        if found is not None:
            return found, line, len(probed)
    for path_text, line in candidates:
        needle = _suffix_needle(path_text, context)
        if needle is None:
            continue
        found = _unique_suffix_hit(needle, context, git_cache, consider)
        if found is not None:
            return found, line, len(probed)
    return None, None, len(probed)


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


def _path_candidates(text: str) -> tuple[tuple[str, int | None], ...]:
    seen: set[str] = set()
    candidates: list[tuple[str, int | None]] = []
    for variant in _candidate_texts(text):
        path_text, line = _split_line_suffix(variant)
        if not path_text or path_text in seen:
            continue
        seen.add(path_text)
        candidates.append((path_text, line))
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


def _split_line_suffix(text: str) -> tuple[str, int | None]:
    for pattern in (_LINE_COL_SUFFIX_RE, _LINE_SUFFIX_RE):
        match = pattern.fullmatch(text)
        if match is None:
            continue
        path_text = match.group(1)
        if _TRAILING_LINE_DIGITS_RE.search(path_text):
            continue
        return path_text, int(match.group(2))
    return text, None


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

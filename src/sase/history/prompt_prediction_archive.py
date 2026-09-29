"""Archive-source rows for next-word prompt prediction.

Builds :class:`PromptPredictionRow` inputs from the enabled projects'
canonical agents-sidecar prompt archives (``prompts/<YYYYMM>/*.md``) through
the Rust-backed :func:`prompt_archive_inventory` facade.

Each kept row carries the sidecar's sync project key and the document's
mtime epoch with ``origin=None``, so the core's legacy origin heuristic
(``looks_generated``) still excludes machine-generated archive prompts at
compile time: the inventory schema records no launch-topology field, so
there is nothing archive-side to filter top-level user-launched prompts on.

Volume is bounded to the 6 most recent month directories per sidecar and
1.5M whitespace tokens newest first. Paragraphs are deduped by normalized
hash within the archive (swarm copies) and against local history rows, then
rejoined per document; documents left empty are dropped.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from sase.core.prompt_prediction_wire import PromptPredictionRow

log = logging.getLogger(__name__)

#: Most recent month directories read per agents-sidecar archive.
ARCHIVE_RECENT_MONTHS: Final = 6

#: Newest-first whitespace-token budget across all archive rows.
ARCHIVE_TOKEN_BUDGET: Final = 1_500_000

#: Composition weight for the pruned archive corpus in the live model.
ARCHIVE_CORPUS_WEIGHT: Final = 0.25

#: Sources the archive corpus is rebuilt from, oldest throttling knob aside.
ARCHIVE_SOURCE_ROLE: Final = "archive"

#: Minimum seconds between archive corpus rebuilds in the TUI warm cache.
ARCHIVE_REBUILD_MIN_INTERVAL_SECONDS: Final = 600

#: Staleness token for the archive row inputs: one ``(project_key, month,
#: month-dir mtime_ns, markdown count)`` entry per recent month directory.
ArchivePredictionToken = tuple[tuple[str, str, int, int], ...]

_MONTH_RE: Final = re.compile(r"^\d{6}$")

#: Markdown reference-style link definitions (rendered link tables), e.g.
#: ``[1]: https://github.com/...`` or a bare ``[1]:`` label with the URL on
#: the next indented line. The Rust inventory body already excludes the
#: header bullets; these trailing tables are the remaining non-prose.
_LINK_DEFINITION_RE: Final = re.compile(r"^[ ]{0,3}\[[^\]\n]+\]:([ \t]*\S.*)?$")
_INDENTED_CONTINUATION_RE: Final = re.compile(r"^[ \t]+\S.*$")

_PARAGRAPH_SPLIT_RE: Final = re.compile(r"\n[ \t]*\n")
_INNER_WHITESPACE_RE: Final = re.compile(r"\s+")
_COLLAPSE_BLANKS_RE: Final = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")


@dataclass(frozen=True, slots=True)
class _ArchivePredictionTarget:
    """One enabled project's agents-sidecar archive selected for extraction."""

    project_key: str
    sidecar_path: Path


def _list_archive_prediction_targets() -> tuple[_ArchivePredictionTarget, ...]:
    """Return enabled projects whose agents-sidecar checkout exists.

    Never raises: sync/inventory failures yield an empty selection and a
    debug log, so the prediction cache degrades to history-only.
    """
    try:
        from sase.agents_sync.targets import resolve_sync_targets
    except Exception:
        log.debug("Archive prediction targets unavailable", exc_info=True)
        return ()
    try:
        selection = resolve_sync_targets()
    except Exception:
        log.debug("Archive prediction target resolution failed", exc_info=True)
        return ()
    targets: list[_ArchivePredictionTarget] = []
    for target in selection.targets:
        try:
            exists = target.sidecar_path.is_dir()
        except OSError:
            exists = False
        if exists:
            targets.append(
                _ArchivePredictionTarget(
                    project_key=target.project_key,
                    sidecar_path=target.sidecar_path,
                )
            )
    return tuple(targets)


def _clean_archive_body(body: str) -> str:
    """Strip rendered link tables from an archive document body."""
    lines: list[str] = []
    skip_continuation = False
    for line in body.splitlines():
        if _LINK_DEFINITION_RE.match(line):
            # A bare ``[label]:`` label keeps its URL on the next indented
            # line; an inline definition carries it on the same line.
            skip_continuation = line.rstrip().endswith(":")
            continue
        if skip_continuation:
            skip_continuation = False
            if _INDENTED_CONTINUATION_RE.match(line):
                continue
        lines.append(line)
    return _COLLAPSE_BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def _split_archive_paragraphs(text: str) -> list[str]:
    """Split cleaned archive text into non-empty paragraphs."""
    return [
        paragraph.strip()
        for paragraph in _PARAGRAPH_SPLIT_RE.split(text)
        if paragraph.strip()
    ]


def _normalize_archive_paragraph(paragraph: str) -> str:
    """Return the dedup key for one paragraph (whitespace-folded, casefolded)."""
    return _INNER_WHITESPACE_RE.sub(" ", paragraph.strip().casefold())


def _paragraph_hash(normalized: str) -> str:
    """Return the dedup digest for one normalized paragraph."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _history_paragraph_hashes(texts: list[str]) -> set[str]:
    """Return paragraph digests for local history texts (the dedup seed)."""
    hashes: set[str] = set()
    for text in texts:
        for paragraph in _split_archive_paragraphs(_clean_archive_body(text)):
            normalized = _normalize_archive_paragraph(paragraph)
            if normalized:
                hashes.add(_paragraph_hash(normalized))
    return hashes


def archive_prediction_source_token(
    targets: tuple[_ArchivePredictionTarget, ...] | None = None,
) -> tuple[tuple[str, str, int, int], ...]:
    """Return a cheap staleness token for the archive row inputs.

    One entry per ``(project_key, month)`` with the month directory's mtime
    and markdown-file count. No document is opened, so the warm cache can
    poll this without disk-heavy reads.
    """
    resolved = _list_archive_prediction_targets() if targets is None else targets
    token: list[tuple[str, str, int, int]] = []
    for target in resolved:
        prompts_root = target.sidecar_path / "prompts"
        try:
            month_dirs = sorted(
                path
                for path in prompts_root.iterdir()
                if path.is_dir() and _MONTH_RE.match(path.name)
            )
        except OSError:
            continue
        for month_dir in month_dirs[-ARCHIVE_RECENT_MONTHS:]:
            token.append(
                (
                    target.project_key,
                    month_dir.name,
                    _dir_mtime_ns(month_dir),
                    _markdown_file_count(month_dir),
                )
            )
    return tuple(token)


def build_archive_prediction_rows(
    *,
    history_texts: list[str] | None = None,
    targets: tuple[_ArchivePredictionTarget, ...] | None = None,
    inventory_fn: Callable[[Path], Iterable[Any]] | None = None,
) -> list[PromptPredictionRow]:
    """Build deduped prediction rows from the canonical prompt archives.

    *history_texts* seeds paragraph dedup against local history (defaults
    to the sharded history rows). *targets* defaults to the enabled
    projects' sidecars. *inventory_fn* maps a sidecar path to archive
    documents and exists for tests; production passes ``None`` to use the
    Rust-backed facade.
    """
    seen = _history_paragraph_hashes(
        history_texts
        if history_texts is not None
        else [row.text for row in _load_history_rows()]
    )
    resolved = _list_archive_prediction_targets() if targets is None else targets
    candidates: list[tuple[str, int, str, _ArchivePredictionTarget, Any]] = []
    for target in resolved:
        for document in _inventory_documents(target, inventory_fn):
            if document.parse_error is not None:
                continue
            if not _MONTH_RE.match(document.month):
                continue
            candidates.append(
                (
                    document.month,
                    _document_mtime(document),
                    document.relpath,
                    target,
                    document,
                )
            )
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    allowed_months = _recent_months(candidates)
    rows: list[PromptPredictionRow] = []
    tokens = 0
    for month, mtime, _relpath, target, document in candidates:
        if month not in allowed_months[target.project_key]:
            continue
        kept = _dedup_document_paragraphs(_clean_archive_body(document.body), seen)
        if not kept:
            continue
        text = "\n\n".join(kept)
        tokens += len(text.split())
        if tokens > ARCHIVE_TOKEN_BUDGET:
            log.info(
                "Archive prediction rows stopped after token budget=%s",
                ARCHIVE_TOKEN_BUDGET,
            )
            break
        rows.append(
            PromptPredictionRow(
                text=text,
                epoch_seconds=mtime or _month_start_epoch(month),
                project=target.project_key,
                origin=None,
                cancelled=False,
            )
        )
    return rows


def _load_history_rows() -> list[PromptPredictionRow]:
    try:
        from sase.history.prompt_prediction_rows import build_prompt_prediction_rows

        return build_prompt_prediction_rows()
    except Exception:
        log.debug("Archive history seed unavailable", exc_info=True)
        return []


def _inventory_documents(
    target: _ArchivePredictionTarget,
    inventory_fn: Callable[[Path], Iterable[Any]] | None,
) -> list[Any]:
    if inventory_fn is not None:
        return list(inventory_fn(target.sidecar_path))
    from sase.core.prompt_archive_facade import prompt_archive_inventory

    # Bound reads to the recent month directories so the filter in
    # ``build_archive_prediction_rows`` does not first load every month's
    # bodies. The facade accepts ``month=``; fall back to one unbounded
    # read when it does not.
    try:
        prompts_root = target.sidecar_path / "prompts"
        month_dirs = sorted(
            path
            for path in prompts_root.iterdir()
            if path.is_dir() and _MONTH_RE.match(path.name)
        )
    except OSError:
        month_dirs = []
    if not month_dirs:
        try:
            return list(prompt_archive_inventory(target.sidecar_path))
        except Exception:
            log.debug(
                "Archive inventory failed for %s", target.project_key, exc_info=True
            )
            return []
    documents: list[Any] = []
    for month_dir in month_dirs[-ARCHIVE_RECENT_MONTHS:]:
        try:
            try:
                batch = prompt_archive_inventory(
                    target.sidecar_path, month=month_dir.name
                )
            except TypeError:
                return list(prompt_archive_inventory(target.sidecar_path))
        except Exception:
            log.debug(
                "Archive inventory failed for %s", target.project_key, exc_info=True
            )
            continue
        documents.extend(batch)
    return documents


def _recent_months(
    candidates: list[tuple[str, int, str, _ArchivePredictionTarget, Any]],
) -> dict[str, set[str]]:
    months: dict[str, set[str]] = {}
    for month, _mtime, _relpath, target, _document in candidates:
        months.setdefault(target.project_key, set()).add(month)
    return {
        project_key: set(sorted(values)[-ARCHIVE_RECENT_MONTHS:])
        for project_key, values in months.items()
    }


def _dedup_document_paragraphs(body: str, seen: set[str]) -> list[str]:
    kept: list[str] = []
    for paragraph in _split_archive_paragraphs(body):
        normalized = _normalize_archive_paragraph(paragraph)
        if not normalized:
            continue
        digest = _paragraph_hash(normalized)
        if digest in seen:
            continue
        seen.add(digest)
        kept.append(paragraph)
    return kept


def _document_mtime(document: Any) -> int:
    try:
        return int(document.path.stat().st_mtime)
    except OSError:
        return 0


def _month_start_epoch(month: str) -> int:
    try:
        return int(datetime(int(month[:4]), int(month[4:6]), 1).timestamp())
    except ValueError:
        return 0


def _dir_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _markdown_file_count(month_dir: Path) -> int:
    try:
        return sum(
            1
            for child in month_dir.iterdir()
            if child.is_file() and child.suffix == ".md"
        )
    except OSError:
        return -1


__all__ = [
    "ARCHIVE_CORPUS_WEIGHT",
    "ARCHIVE_REBUILD_MIN_INTERVAL_SECONDS",
    "ARCHIVE_RECENT_MONTHS",
    "ARCHIVE_SOURCE_ROLE",
    "ARCHIVE_TOKEN_BUDGET",
    "ArchivePredictionToken",
    "archive_prediction_source_token",
    "build_archive_prediction_rows",
]

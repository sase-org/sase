"""Handler for the ``sase pager`` command."""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
import sys
from typing import TextIO

from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.flag import link_pager_enabled
from sase.pager.resolve import LinkTarget, LinkTargetKind, resolve_ref


class _PagerInputError(Exception):
    """Raised when a CLI pager input cannot become a document section."""


def handle_pager_command(args: argparse.Namespace) -> int:
    """Handle ``sase pager``."""
    try:
        document = _build_pager_document(
            getattr(args, "inputs", ()),
            title=getattr(args, "title", None),
        )
    except _PagerInputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    links_enabled = getattr(args, "links", "auto") != "never"
    if _should_write_plain(args):
        _write_document_plain(document)
        return 0

    with _textual_stdin() as has_stdin:
        if not has_stdin:
            _write_document_plain(document)
            return 0
        try:
            _run_pager_app(document, links_enabled=links_enabled)
        except Exception:
            _write_document_plain(document)
    return 0


def _build_pager_document(
    inputs: Sequence[str],
    *,
    title: str | None = None,
) -> PagerDocument:
    """Build one pager document from CLI refs/paths or stdin."""
    values = tuple(inputs)
    if not values or values == ("-",):
        resolved_title = title or "stdin"
        return PagerDocument(
            sections=(
                PagerSection(
                    identity="stdin",
                    title=resolved_title,
                    kind="stdin",
                    body=sys.stdin.read(),
                ),
            ),
            title=resolved_title,
            origin=PagerOrigin.FILE,
        )
    if "-" in values:
        raise _PagerInputError("'-' must be the only pager input when reading stdin")

    documents = tuple(_document_for_input(value) for value in values)
    sections = tuple(section for document in documents for section in document.sections)
    return PagerDocument(
        sections=sections,
        title=title or _input_document_title(values),
        origin=_combined_origin(documents),
    )


def _document_for_input(value: str) -> PagerDocument:
    try:
        target = resolve_ref(value)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _PagerInputError(f"could not resolve {value!r}: {exc}") from exc
    if target is None:
        raise _PagerInputError(f"could not resolve {value!r}")
    document = _document_for_target(value, target)
    if document is None:
        raise _PagerInputError(f"could not render {value!r} as text")
    return document


def _document_for_target(value: str, target: LinkTarget) -> PagerDocument | None:
    if target.document is not None:
        return target.document
    if target.kind is LinkTargetKind.MEDIA:
        return _media_document(value, target)
    return None


def _media_document(value: str, target: LinkTarget) -> PagerDocument:
    lines = [f"reference: {value}", "kind: media"]
    for spec in target.media_specs:
        lines.append(f"path: {spec.path}")
        lines.append(f"view_mode: {spec.kind}")
    body = "\n".join(lines) + "\n"
    return PagerDocument(
        sections=(
            PagerSection(
                identity=value,
                title=value,
                kind="file",
                body=body,
                subject_ref=value,
            ),
        ),
        title=value,
        origin=PagerOrigin.FILE,
    )


def _input_document_title(values: Sequence[str]) -> str:
    if len(values) == 1:
        return values[0]
    return f"{len(values)} inputs"


def _combined_origin(documents: Sequence[PagerDocument]) -> PagerOrigin:
    origins = {document.origin for document in documents}
    if len(origins) == 1:
        return next(iter(origins))
    return PagerOrigin.FILE


def _should_write_plain(args: argparse.Namespace) -> bool:
    if getattr(args, "plain", False):
        return True
    if not sys.stdout.isatty():
        return True
    if not _term_supports_pager_app():
        return True
    return not link_pager_enabled()


def _term_supports_pager_app() -> bool:
    from os import environ

    term = environ.get("TERM")
    return term is not None and term != "dumb"


@contextmanager
def _textual_stdin() -> Iterator[bool]:
    if sys.stdin.isatty():
        yield True
        return

    try:
        tty = open("/dev/tty", encoding="utf-8", errors="replace")
    except OSError:
        yield False
        return

    original_stdin: TextIO = sys.stdin
    try:
        sys.stdin = tty
        yield True
    finally:
        sys.stdin = original_stdin
        tty.close()


def _run_pager_app(document: PagerDocument, *, links_enabled: bool) -> None:
    from sase.pager.app import SasePager

    SasePager(document, links_enabled=links_enabled).run()


def _write_document_plain(document: PagerDocument) -> None:
    sys.stdout.write(_render_document_plain(document))


def _render_document_plain(document: PagerDocument) -> str:
    """Render a pager document as plain terminal text."""
    if not document.sections:
        return ""
    if len(document.sections) == 1:
        return _ensure_trailing_newline(document.sections[0].plain_text)

    total = len(document.sections)
    blocks = []
    for index, section in enumerate(document.sections, start=1):
        body = section.plain_text.rstrip("\n")
        blocks.append(f"-- {index}/{total}: {section.title} --\n{body}")
    return "\n\n".join(blocks) + "\n"


def _ensure_trailing_newline(text: str) -> str:
    return text if not text or text.endswith("\n") else f"{text}\n"


__all__ = ["handle_pager_command"]

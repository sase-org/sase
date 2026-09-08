"""Terminal pager support for already-rendered CLI text."""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
from enum import StrEnum
from typing import TYPE_CHECKING

from rich.cells import cell_len

if TYPE_CHECKING:
    from sase.pager.document import PagerDocument
    from sase.pager.syntax_policy import PagerSyntaxSession

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


class PagerMode(StrEnum):
    """User-facing pager modes."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


def resolve_pager_mode(value: str) -> PagerMode:
    """Resolve the parser string into one concrete pager mode."""
    return PagerMode(value)


def page_or_print(
    text: str,
    *,
    mode: PagerMode | str,
    document: PagerDocument | None = None,
    syntax_session: PagerSyntaxSession | None = None,
) -> None:
    """Write *text* directly or hand it to the SASE pager."""
    resolved_mode = mode if isinstance(mode, PagerMode) else resolve_pager_mode(mode)
    if not _should_page(text, mode=resolved_mode):
        _write_direct(text)
        return

    try:
        _run_sase_pager(text, document=document, syntax_session=syntax_session)
    except Exception:
        _write_direct(text)


def _should_page(
    text: str,
    *,
    mode: PagerMode,
) -> bool:
    if mode is PagerMode.NEVER:
        return False
    if not sys.stdout.isatty() or not _term_supports_paging():
        return False

    if mode is PagerMode.AUTO:
        if os.environ.get("SASE_AGENT") is not None:
            return False
        size = shutil.get_terminal_size(fallback=(80, 24))
        if _estimated_display_rows(text, columns=size.columns) <= size.lines - 1:
            return False
    return True


def _term_supports_paging() -> bool:
    term = os.environ.get("TERM")
    return term is not None and term != "dumb"


def _run_sase_pager(
    text: str,
    *,
    document: PagerDocument | None,
    syntax_session: PagerSyntaxSession | None = None,
) -> None:
    from sase.pager.app import SasePager
    from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
    from sase.pager.link_context import default_link_context
    from sase.pager.syntax_policy import (
        classify_source,
        pager_syntax_session_from_config,
    )

    session = (
        syntax_session
        if syntax_session is not None
        else pager_syntax_session_from_config()
    )
    pager_document = document
    if pager_document is None:
        from sase.pager.known_kinds import known_kinds_from_link_context

        context = default_link_context()
        pager_document = PagerDocument(
            sections=(
                PagerSection(
                    identity="stdin",
                    title="stdin",
                    kind="stdin",
                    body=text,
                    raw_source=classify_source(category="stdin", source=text),
                    known_kinds=known_kinds_from_link_context(context),
                ),
            ),
            title="stdin",
            origin=PagerOrigin.FILE,
            link_context=context,
        )
    SasePager(pager_document, syntax_session=session).run()


def _estimated_display_rows(text: str, *, columns: int) -> int:
    columns = max(columns, 1)
    rows = 0
    for line in text.splitlines():
        plain = _SGR_RE.sub("", line)
        rows += max(1, math.ceil(cell_len(plain) / columns))
    return rows


def _write_direct(text: str) -> None:
    sys.stdout.write(text)


__all__ = [
    "PagerMode",
    "page_or_print",
    "resolve_pager_mode",
]

"""Session controls and producer-side source classification for pager syntax.

Language identity stays in the Rust facade; this module is the production
caller that turns CLI/config/color policy and adapter provenance into
``RawSourceSpec`` values. Direct/plain output paths must not import the
lexer or schedule syntax work.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import mimetypes
import os
from pathlib import Path

from pygments.util import ClassNotFound  # type: ignore[import-untyped]

from sase.core.rust import require_rust_binding
from sase.core.source_language_facade import resolve_source_language
from sase.pager.document import PagerDocument, RawSourceSpec
from sase.pager.syntax import resolve_pygments_alias

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
_LEGACY_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".json",
        ".yml",
        ".yaml",
        ".toml",
        ".xml",
        ".rst",
        ".py",
        ".sh",
    }
)
_MARKDOWN_ARTIFACT_KINDS = frozenset({"chat", "markdown", "plan", "document"})
_FORMATTED_KIND_TYPES = frozenset({"bead", "stitch", "commit"})


class PagerSyntaxError(ValueError):
    """Raised when ``--syntax`` names an unknown Pygments alias."""


@dataclass(frozen=True, slots=True)
class PagerSyntaxSession:
    """Session-wide syntax and color controls.

    ``syntax_enabled`` stays false across follow/back/forward when the user
    chose ``none``, config ``never``, or ``--color never``. Explicit lexer
    overrides are baked into the initial document instead of this object so
    newly followed targets keep their own detection.
    """

    syntax_enabled: bool = True
    color_enabled: bool = True


@dataclass(frozen=True, slots=True)
class _CliSyntaxResolution:
    """CLI ``--syntax``/``--color`` resolution for one ``sase pager`` run."""

    session: PagerSyntaxSession
    explicit_language: str | None = None
    apply_override: bool = False


def _color_enabled_for_mode(color_mode: str) -> bool:
    """Resolve ``auto``/``always``/``never`` against ``NO_COLOR``."""
    mode = (color_mode or "auto").strip().lower()
    if mode == "always":
        return True
    if mode == "never":
        return False
    return os.environ.get("NO_COLOR") is None


def pager_syntax_session_from_config(
    *,
    color_enabled: bool | None = None,
) -> PagerSyntaxSession:
    """Resolve ``pager.syntax`` once, off render/key paths.

    ``color_enabled`` is the host terminal policy. ``None`` means auto
    (honor ``NO_COLOR``). Color off always disables the added syntax layer.
    """
    resolved_color = (
        _color_enabled_for_mode("auto") if color_enabled is None else color_enabled
    )
    if not resolved_color:
        return PagerSyntaxSession(syntax_enabled=False, color_enabled=False)
    from sase.config import get_pager_syntax

    return PagerSyntaxSession(
        syntax_enabled=get_pager_syntax() != "never",
        color_enabled=True,
    )


def resolve_cli_syntax(
    *,
    syntax: str | None,
    color: str,
) -> _CliSyntaxResolution:
    """Validate CLI syntax/color before stdin is consumed.

    ``syntax is None`` means the flag was omitted: config ``pager.syntax``
    applies. An explicit ``auto`` overrides config ``never``. ``none`` is a
    session disable, distinct from the ``text``/``plain`` aliases that leave
    source visible without a language chip.
    """
    color_enabled = _color_enabled_for_mode(color)
    if not color_enabled:
        _validate_syntax_alias_if_explicit(syntax)
        return _CliSyntaxResolution(
            session=PagerSyntaxSession(syntax_enabled=False, color_enabled=False)
        )
    if syntax is None:
        return _CliSyntaxResolution(session=pager_syntax_session_from_config())
    key = syntax.strip().lower()
    if key == "none":
        return _CliSyntaxResolution(
            session=PagerSyntaxSession(syntax_enabled=False, color_enabled=True)
        )
    if key == "auto":
        return _CliSyntaxResolution(
            session=PagerSyntaxSession(syntax_enabled=True, color_enabled=True)
        )
    language = _require_pygments_alias(syntax)
    return _CliSyntaxResolution(
        session=PagerSyntaxSession(syntax_enabled=True, color_enabled=True),
        explicit_language=language,
        apply_override=True,
    )


def classify_source(
    *,
    category: str,
    source: str,
    logical_filename: str | None = None,
) -> RawSourceSpec | None:
    """Return raw-source metadata for a body the pager will actually show."""
    if category == "formatted":
        return None
    if "\x00" in source:
        return None
    result = resolve_source_language(
        category=category,
        logical_filename=logical_filename,
        prefix=_bounded_prefix(source),
    )
    if result.reason == "ineligible":
        return None
    return RawSourceSpec(language=result.language, eligible=True)


def apply_explicit_syntax(
    document: PagerDocument,
    language: str | None,
) -> PagerDocument:
    """Force *language* on every eligible raw section of the initial document."""
    sections = tuple(
        section
        if section.raw_source is None
        else replace(
            section,
            raw_source=RawSourceSpec(language=language, eligible=True),
        )
        for section in document.sections
    )
    return replace(document, sections=sections)


def preview_has_nul(path: Path, *, limit: int | None = None) -> bool:
    """Return whether a bounded byte preview of *path* contains a NUL."""
    budget = _prefix_budget_bytes() if limit is None else limit
    try:
        with path.open("rb") as handle:
            preview = handle.read(budget)
    except OSError:
        return False
    return b"\x00" in preview


def is_openable_text_path(
    path: Path,
    *,
    logical_filename: str | None = None,
    mime: str | None = None,
) -> bool:
    """Return whether *path* should enter a pager text section.

    Combines the shared Rust filename/shebang policy with the historical
    MIME/suffix gate, then excludes NUL-bearing binaries. I/O is a bounded
    preview plus, when needed, a MIME guess — never a second language policy.
    """
    if preview_has_nul(path):
        return False
    filename = logical_filename if logical_filename is not None else str(path)
    result = resolve_source_language(
        category="raw_file",
        logical_filename=filename,
        prefix=_read_prefix_text(path),
    )
    if result.supported_text or result.language is not None:
        return True
    return _legacy_mime_text(path, mime=mime)


def artifact_syntax_category(
    *,
    kind_type: str,
    kind: str | None,
) -> str:
    """Return the Rust source category for an artifact pager body."""
    if kind_type in _FORMATTED_KIND_TYPES:
        return "formatted"
    if kind in _MARKDOWN_ARTIFACT_KINDS or kind_type in _MARKDOWN_ARTIFACT_KINDS:
        return "markdown_document"
    return "raw_file"


def _prefix_budget_bytes() -> int:
    """Return the Rust-owned prefix inspection budget."""
    return int(require_rust_binding("source_language_prefix_budget_bytes")())


def _validate_syntax_alias_if_explicit(syntax: str | None) -> None:
    if syntax is None:
        return
    key = syntax.strip().lower()
    if key in {"", "auto", "none"}:
        return
    _require_pygments_alias(syntax)


def _require_pygments_alias(syntax: str) -> str | None:
    try:
        return resolve_pygments_alias(syntax)
    except ClassNotFound as exc:
        raise PagerSyntaxError(
            f"unknown syntax alias {syntax!r}; use auto, none, or a Pygments lexer name"
        ) from exc


def _bounded_prefix(source: str) -> str:
    budget = _prefix_budget_bytes()
    encoded = source.encode("utf-8")
    if len(encoded) <= budget:
        return source
    return encoded[:budget].decode("utf-8", errors="ignore")


def _read_prefix_text(path: Path) -> str:
    budget = _prefix_budget_bytes()
    try:
        with path.open("rb") as handle:
            preview = handle.read(budget)
    except OSError:
        return ""
    if b"\x00" in preview:
        return ""
    return preview.decode("utf-8", errors="replace")


def _legacy_mime_text(path: Path, *, mime: str | None) -> bool:
    suffix = path.suffix.lower()
    if suffix in _LEGACY_TEXT_SUFFIXES:
        return True
    guessed = mime if mime is not None else mimetypes.guess_type(str(path))[0]
    if guessed is None:
        return False
    return guessed.startswith(_TEXT_MIME_PREFIXES) or guessed in _TEXT_MIME_TYPES


__all__ = [
    "PagerSyntaxError",
    "PagerSyntaxSession",
    "apply_explicit_syntax",
    "artifact_syntax_category",
    "classify_source",
    "is_openable_text_path",
    "pager_syntax_session_from_config",
    "preview_has_nul",
    "resolve_cli_syntax",
]

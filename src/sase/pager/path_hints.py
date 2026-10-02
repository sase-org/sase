"""Textual-free file-path matchers shared by the pager link scanner.

Moved out of :mod:`sase.ace.tui.widgets.prompt_panel._file_path_hints` so the
cold path (``sase.pager.link_scan``) can scan for file links without importing
the agent prompt-panel package. The original module re-exports every name here,
so ACE callers and behavior are unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator
import re

_FILE_PATH_ALTERNATIVES = (
    # Absolute paths: /foo/bar or ~/foo/bar
    r"(?:~?/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Relative paths with explicit prefix: ./foo or ../foo
    r"(?:\.{1,2}/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Dot-directory paths: .sase/foo.ext
    r"(?:\.[\w\-]+/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Bare relative paths with extension: dir/file.ext
    r"(?:[\w\-]+/[\w.+\-/]*\.[\w]+)"
)
_FILE_PATH_PATTERN = (
    r"(?<![/\w@.])"  # Not preceded by word char, /, @, or .
    r"(@?)"  # Group 1: optional @ prefix
    r"("  # Group 2: the file path
    f"{_FILE_PATH_ALTERNATIVES}"
    r")"
)
# Pager-only: Rust owns this line-location grammar; this matcher only keeps
# scan_bounded_links from truncating a recognized location suffix in half.
_PAGER_LINK_LOCATION_SUFFIX = (
    r"(?:"
    r"(?::\d+(?::\d+)?(?:-\d+)?)"
    r"|"
    r"(?:#[Ll]\d+(?:[Cc]\d+)?(?:-[Ll]?\d+(?:[Cc]\d+)?)?)"
    r")?"
)
_PAGER_FILE_PATH_PATTERN = (
    r"(?<![/\w@.])"
    r"(@?)"
    r"("
    r"(?:"
    f"{_FILE_PATH_ALTERNATIVES}"
    r")"
    r"(?<!\.)"
    f"{_PAGER_LINK_LOCATION_SUFFIX}"
    r")"
)
# Regex to match file paths in text.
# Group 1: optional @ prefix (sase file reference convention)
# Group 2: the actual file path
FILE_PATH_RE = re.compile(_FILE_PATH_PATTERN)
_FILE_PATH_RE = FILE_PATH_RE
HTTP_URL_PATTERN = r"(?<!\w)(?i:https?)://[^\s<>()\[\]{}'\"`]+"
_FILE_PATH_OR_HTTP_URL_RE = re.compile(
    f"(?:{HTTP_URL_PATTERN})|(?:{_FILE_PATH_PATTERN})"
)
_PAGER_FILE_PATH_OR_HTTP_URL_RE = re.compile(
    f"(?:{HTTP_URL_PATTERN})|(?:{_PAGER_FILE_PATH_PATTERN})"
)

FileHintMatcher = Callable[[str], Iterator[re.Match[str]]]


def iter_file_path_matches(content: str) -> Generator[re.Match[str], None, None]:
    """Yield file-path matches that are not contained in HTTP(S) URLs."""
    for match in _FILE_PATH_OR_HTTP_URL_RE.finditer(content):
        if match.group(2) is not None:
            yield match


def iter_pager_file_path_matches(content: str) -> Generator[re.Match[str], None, None]:
    """Yield pager file-path matches with :LINE/:LINE:COL, without sentence dots.

    Opt-in variant of ``iter_file_path_matches``. Only the pager link scanner
    uses it; ACE hint callers keep the original matcher so their output stays
    byte-identical.
    """
    for match in _PAGER_FILE_PATH_OR_HTTP_URL_RE.finditer(content):
        if match.group(2) is not None:
            yield match


def file_hint_match_span(match: re.Match[str]) -> tuple[int, int]:
    """Return the visible token span for a file-hint regex match."""
    return (match.start(1) if match.group(1) else match.start(2), match.end(2))


def has_file_path(content: str) -> bool:
    """Return whether *content* has a file path outside HTTP(S) URLs."""
    return next(iter_file_path_matches(content), None) is not None


__all__ = [
    "FILE_PATH_RE",
    "HTTP_URL_PATTERN",
    "FileHintMatcher",
    "file_hint_match_span",
    "has_file_path",
    "iter_file_path_matches",
    "iter_pager_file_path_matches",
]

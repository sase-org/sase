"""Natural-language word extraction, spelling, and definition adapters."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

_MAX_WORD_LENGTH = 64
_ASPELL_TIMEOUT_SECONDS = 3.0
_DICT_TIMEOUT_SECONDS = 5.0
_DICT_NO_MATCH_EXIT_CODE = 20
_CONNECTORS = frozenset({"'", "-"})

# The salmon used for both the spellcheck correction panel and the sticky
# misspelling underline in the prompt input, so the two visibly match.
MISSPELLING_COLOR = "#FF8787"

_DefinitionStatus = Literal["ok", "no_match", "unavailable", "error"]
_SpellCheckStatus = Literal["correct", "misspelled", "unavailable", "error"]
_Runner = Callable[..., subprocess.CompletedProcess[str]]

_DEFINITION_HEADER_RE = re.compile(
    r"^From (?P<source>.+?) \[(?P<database>[^\]]+)\]:[ \t]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class WordSpan:
    """A natural-language word and its location within one document row."""

    word: str
    row: int
    start_col: int
    end_col: int


@dataclass(frozen=True)
class SpellCheckResult:
    """The parsed outcome of one aspell pipe-protocol query."""

    status: _SpellCheckStatus
    suggestions: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class DefinitionSection:
    """One dictionary source returned by the DICT client."""

    source: str
    body: str


@dataclass(frozen=True)
class DefinitionResult:
    """The parsed outcome of one DICT definition query."""

    status: _DefinitionStatus
    sections: tuple[DefinitionSection, ...] = ()
    detail: str = ""


def extract_lookup_word(
    line: str,
    row: int,
    col: int,
) -> WordSpan | None:
    """Extract the plain-English word under *col* in one prompt line.

    Unicode letters are accepted. ASCII apostrophes and hyphens are accepted
    only between letters. Runs containing a digit or underscore are treated as
    identifiers rather than natural-language words.
    """
    if col < 0 or col >= len(line):
        return None

    current = line[col]
    if not current.isalpha():
        if current not in _CONNECTORS or not _is_interior_connector(line, col):
            return None

    start = col
    while start > 0 and _is_candidate_char(line[start - 1]):
        start -= 1

    end = col + 1
    while end < len(line) and _is_candidate_char(line[end]):
        end += 1

    validated = _validate_word_run(line, start, end)
    if validated is None:
        return None
    start, end, word = validated
    return WordSpan(word=word, row=row, start_col=start, end_col=end)


def natural_word_ranges(text: str) -> Iterator[tuple[int, int, str]]:
    """Yield ``(start, end, word)`` for every K-targetable word in *text*.

    Offsets are absolute Python character offsets over the whole document.
    Word runs never cross newlines, since ``\\n`` is neither alpha nor a
    connector. Shares :func:`_validate_word_run` with :func:`extract_lookup_word`
    so the cursor-targeted and whole-document rules cannot diverge.
    """
    length = len(text)
    index = 0
    while index < length:
        if not _is_candidate_char(text[index]):
            index += 1
            continue
        start = index
        end = index + 1
        while end < length and _is_candidate_char(text[end]):
            end += 1
        validated = _validate_word_run(text, start, end)
        if validated is not None:
            yield validated
        index = end


def _validate_word_run(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    """Trim connectors and validate a raw candidate run of *text*.

    A candidate run is a maximal span of alpha/digit/underscore/connector
    characters. Returns the trimmed ``(start, end, word)`` or ``None`` when the
    run contains a digit/underscore, is empty, exceeds the length cap, or has a
    non-interior connector.
    """
    candidate = text[start:end]
    if any(char.isdigit() or char == "_" for char in candidate):
        return None

    while start < end and text[start] in _CONNECTORS:
        start += 1
    while end > start and text[end - 1] in _CONNECTORS:
        end -= 1

    word = text[start:end]
    if not word or len(word) > _MAX_WORD_LENGTH:
        return None
    if not all(
        char.isalpha() or (char in _CONNECTORS and _is_interior_connector(word, i))
        for i, char in enumerate(word)
    ):
        return None

    return start, end, word


def check_spelling(
    word: str,
    *,
    runner: _Runner = subprocess.run,
) -> SpellCheckResult:
    """Check one word with GNU aspell's Ispell-compatible pipe protocol."""
    if shutil.which("aspell") is None:
        return SpellCheckResult(status="unavailable")

    try:
        completed = runner(
            ["aspell", "-a", "--encoding=utf-8", "--lang=en_US"],
            input=f"{word}\n",
            capture_output=True,
            text=True,
            timeout=_ASPELL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SpellCheckResult(
            status="error",
            detail="aspell timed out after 3 seconds",
        )
    except OSError as exc:
        return SpellCheckResult(status="error", detail=_one_line(str(exc)))

    if completed.returncode != 0:
        return SpellCheckResult(
            status="error",
            detail=_command_error_detail("aspell", completed),
        )

    response = _first_aspell_response_line(completed.stdout)
    if response is None:
        return SpellCheckResult(
            status="error",
            detail="aspell returned no spelling result",
        )

    marker = response[0]
    if marker in {"*", "+", "-"}:
        return SpellCheckResult(status="correct")
    if marker == "#":
        return SpellCheckResult(status="misspelled")
    if marker in {"&", "?"}:
        suggestions_text = response.partition(":")[2]
        suggestions = tuple(
            suggestion.strip()
            for suggestion in suggestions_text.split(",")
            if suggestion.strip()
        )
        return SpellCheckResult(
            status="misspelled",
            suggestions=suggestions,
        )

    return SpellCheckResult(
        status="error",
        detail=f"aspell returned an unknown response: {_one_line(response)}",
    )


def look_up_definitions(
    word: str,
    *,
    runner: _Runner = subprocess.run,
) -> DefinitionResult:
    """Look up one word with the DICT protocol client."""
    if shutil.which("dict") is None:
        return DefinitionResult(status="unavailable")

    try:
        completed = runner(
            ["dict", "--", word],
            capture_output=True,
            text=True,
            timeout=_DICT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DefinitionResult(
            status="error",
            detail="dict timed out after 5 seconds",
        )
    except OSError as exc:
        return DefinitionResult(status="error", detail=_one_line(str(exc)))

    if completed.returncode == _DICT_NO_MATCH_EXIT_CODE:
        return DefinitionResult(
            status="no_match",
            detail=_command_error_detail("dict", completed, fallback=""),
        )
    if completed.returncode != 0:
        return DefinitionResult(
            status="error",
            detail=_command_error_detail("dict", completed),
        )

    sections = _parse_definition_sections(completed.stdout)
    if not sections:
        return DefinitionResult(
            status="error",
            detail="dict returned no recognizable definitions",
        )
    return DefinitionResult(status="ok", sections=sections)


def _is_candidate_char(char: str) -> bool:
    return char.isalpha() or char.isdigit() or char == "_" or char in _CONNECTORS


def _is_interior_connector(text: str, index: int) -> bool:
    return (
        0 < index < len(text) - 1
        and text[index - 1].isalpha()
        and text[index + 1].isalpha()
    )


def _first_aspell_response_line(stdout: str) -> str | None:
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line and line[0] in {"*", "+", "-", "&", "?", "#"}:
            return line
    return None


def _parse_definition_sections(stdout: str) -> tuple[DefinitionSection, ...]:
    matches = tuple(_DEFINITION_HEADER_RE.finditer(stdout))
    sections: list[DefinitionSection] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(stdout)
        )
        body = stdout[body_start:body_end].strip("\r\n")
        sections.append(
            DefinitionSection(
                source=match.group("source").strip(),
                body=body,
            )
        )
    return tuple(sections)


def _command_error_detail(
    command: str,
    completed: subprocess.CompletedProcess[str],
    *,
    fallback: str | None = None,
) -> str:
    for output in (completed.stderr, completed.stdout):
        detail = _first_nonempty_line(output)
        if detail:
            return detail
    if fallback is not None:
        return fallback
    return f"{command} exited with status {completed.returncode}"


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return _one_line(line)
    return ""


def _one_line(text: str) -> str:
    return " ".join(text.split())


__all__ = [
    "MISSPELLING_COLOR",
    "DefinitionResult",
    "DefinitionSection",
    "SpellCheckResult",
    "WordSpan",
    "check_spelling",
    "extract_lookup_word",
    "look_up_definitions",
    "natural_word_ranges",
]

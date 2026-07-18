"""Semantic highlighter for AXE-controlled output.

Lumberjack aggregate logs are emitted in a structured shape (see
``sase.axe.lumberjack.Lumberjack._log``), so we can recognize their tokens and
colorize them coherently with the sidebar taxonomy instead of relying on
whatever ANSI escapes the underlying tool happened to inject.

External script output and user background command output stay on the ANSI
fallback path — see :func:`render_axe_output` with ``source_type="ansi"``.
"""

from __future__ import annotations

import re
from typing import Literal

from rich.text import Text

from .lazy_syntax import cap_ansi_output

SourceType = Literal["lumberjack", "ansi"]

# Sidebar taxonomy palette — keep in sync with bgcmd_list.py.
_LUMBERJACK_NAME_STYLE = "bold #FFD700"
_CHOP_NAME_STYLE = "#D7AF87"
_AGENT_LAUNCH_STYLE = "bold #00D7AF"
_PID_STYLE = "#FF87D7"
_DURATION_STYLE = "#00D7AF"
_COUNT_STYLE = "#00D7AF"
_TIMESTAMP_STYLE = "dim"
_BRACKET_STYLE = "dim"

# Status words mapped to severity styles. Lowercase keys are matched
# case-insensitively against word boundaries on the message body.
_STATUS_WORD_STYLES: dict[str, str] = {
    "success": "bold green",
    "failure": "bold red",
    "timeout": "bold yellow",
    "missing": "bold yellow",
    "missing_script": "bold yellow",
    "running": "bold green",
    "stopped": "#FFD700",
    "error": "bold red",
    "skipping": "dim yellow",
    "skipped": "dim yellow",
    "launched": _AGENT_LAUNCH_STYLE,
}

_LJ_LINE_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] "
    r"\[(?P<name>[^\]]+)\] (?P<message>.*)$"
)

_QUOTED_RE = re.compile(r"'([^']+)'")
_PID_SINGLE_RE = re.compile(r"\bPID\s+(\d+)\b")
_PID_PAREN_RE = re.compile(r"\(PID\s+(\d+)\)")
_PIDS_SET_RE = re.compile(r"\bPIDs\s*\{[^}]*\}")
_DURATION_RE = re.compile(r"\b\d+(?:\.\d+)?(?:ms|s)\b")
_EXIT_CODE_RE = re.compile(r"\bexit code\s+(-?\d+)\b", re.IGNORECASE)
_COUNT_RE = re.compile(
    r"(?<![A-Za-z_])(\d+)\s+(cycles?|chops?|errors?|runs?)\b",
    re.IGNORECASE,
)
_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESCAPE_RE = re.compile(r"\x1b[^\n\r]?")
_STRIPPABLE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f]")

# Hash window for tail-biased cache invalidation. Matches the legacy ANSI
# cache so behavior on huge append-only logs is unchanged.
_TAIL_HASH_BYTES = 1024

# Per-(source_id, source_type) cache slot: ``(size, tail_hash, parsed Text)``.
# Including source_type in the key keeps semantic and ANSI renders from
# colliding even when their numeric identity overlaps.
_render_cache: dict[tuple[str, str], tuple[int, int, Text]] = {}


def _tail_hash(s: str) -> int:
    if len(s) <= _TAIL_HASH_BYTES:
        return hash(s)
    return hash(s[-_TAIL_HASH_BYTES:])


def _strip_control_sequences(s: str) -> str:
    """Remove terminal control bytes before semantic parsing."""
    if _STRIPPABLE_CONTROL_RE.search(s) is None:
        return s

    stripped = _OSC_RE.sub("", s)
    stripped = _CSI_RE.sub("", stripped)
    stripped = _ESCAPE_RE.sub("", stripped)
    return _STRIPPABLE_CONTROL_RE.sub("", stripped)


def classify_source(source_id: str) -> SourceType:
    """Heuristically map a cache slot id to its semantic source type.

    Callers that already know the source type should pass it explicitly to
    :func:`render_axe_output`; this helper exists for callers that only have
    the slot id.
    """
    if source_id.startswith("lumberjack:"):
        return "lumberjack"
    return "ansi"


def render_axe_output(
    source_id: str,
    output: str,
    source_type: SourceType = "ansi",
) -> Text:
    """Return a Rich ``Text`` for ``output`` under the given source type.

    Applies tail-biased caching like the legacy ANSI path so an unchanged
    refresh tick reuses the parsed renderable. ``source_id`` and
    ``source_type`` jointly key the cache so the semantic and ANSI render
    of the same numerical id stay in distinct slots.
    """
    capped = cap_ansi_output(output)
    cache_key = (source_id, source_type)
    size = len(capped)
    digest = _tail_hash(capped)
    cached = _render_cache.get(cache_key)
    if cached is not None and cached[0] == size and cached[1] == digest:
        return cached[2]

    if source_type == "lumberjack":
        text = _render_lumberjack_log(_strip_control_sequences(capped))
    else:
        text = Text.from_ansi(capped)

    _render_cache[cache_key] = (size, digest, text)
    return text


def _render_lumberjack_log(output: str) -> Text:
    """Render a lumberjack aggregate log with semantic highlighting."""
    result = Text()
    for line, newline in _split_lines(output):
        result.append_text(_highlight_lumberjack_line(line))
        if newline:
            result.append(newline)
    return result


def _split_lines(output: str) -> list[tuple[str, str]]:
    """Yield ``(line_without_terminator, terminator)`` pairs."""
    parts: list[tuple[str, str]] = []
    for raw in output.splitlines(keepends=True):
        if raw.endswith("\n"):
            parts.append((raw[:-1], "\n"))
        else:
            parts.append((raw, ""))
    return parts


def _highlight_lumberjack_line(line: str) -> Text:
    m = _LJ_LINE_RE.match(line)
    if m is None:
        # Not a structured lumberjack header — still highlight known tokens
        # in the body so error tails (e.g. "exit code 1") read coherently.
        return _highlight_message_body(line)

    prefix = Text()
    prefix.append("[", style=_BRACKET_STYLE)
    prefix.append(m.group("ts"), style=_TIMESTAMP_STYLE)
    prefix.append("] [", style=_BRACKET_STYLE)
    prefix.append(m.group("name"), style=_LUMBERJACK_NAME_STYLE)
    prefix.append("] ", style=_BRACKET_STYLE)
    prefix.append_text(_highlight_message_body(m.group("message")))
    return prefix


def _highlight_message_body(body: str) -> Text:
    """Highlight known tokens inside a message body.

    The body is appended as a single span and then ``highlight_regex`` layers
    style spans over recognized tokens. Spans applied later win on overlap,
    so we order them from most-generic to most-specific (chop names quoted
    after status words, PIDs after durations) where it matters.
    """
    text = Text(body)

    # Counts (e.g. "5 cycles", "3 errors") — apply before status words so a
    # number in "0 errors" stays count-styled while "errors" itself gets the
    # severity coloring.
    text.highlight_regex(_COUNT_RE, _COUNT_STYLE)

    # Durations like "1.5s", "200ms".
    text.highlight_regex(_DURATION_RE, _DURATION_STYLE)

    # Exit code — color the whole token red so failures pop.
    text.highlight_regex(_EXIT_CODE_RE, "bold red")

    # Status words by severity.
    for word, style in _STATUS_WORD_STYLES.items():
        text.highlight_regex(rf"(?i)\b{re.escape(word)}\b", style)

    # PIDs (single, parenthesized, and set forms).
    text.highlight_regex(_PID_SINGLE_RE, _PID_STYLE)
    text.highlight_regex(_PID_PAREN_RE, _PID_STYLE)
    text.highlight_regex(_PIDS_SET_RE, _PID_STYLE)

    # Quoted chop names — apply last so they win over any status-word match
    # that happened to fall inside the quotes.
    text.highlight_regex(_QUOTED_RE, _CHOP_NAME_STYLE)

    return text

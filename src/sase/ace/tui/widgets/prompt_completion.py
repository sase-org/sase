"""Soft live completion helpers for the ACE prompt input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sase.ace.tui.widgets._file_completion_xprompt_args import (
    build_xprompt_arg_completion_candidates,
    effective_xprompt_arg_token,
)
from sase.ace.tui.widgets.directive_completion import (
    build_directive_completion_candidates,
    extract_directive_token_around_cursor,
)
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    build_completion_candidates,
    extract_token_around_cursor,
    is_path_like_token,
)
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_completion_at_cursor,
)
from sase.ace.tui.widgets.xprompt_completion import (
    build_xprompt_completion_candidates,
    extract_xprompt_token_around_cursor,
)

PromptCompletionAutoMode = Literal["off", "soft"]
WordRankingMode = Literal["smart", "recent"]
PlaceholderRankingMode = WordRankingMode


@dataclass(frozen=True, slots=True)
class PromptCompletionSettings:
    """Parsed prompt completion settings for the TUI prompt bar."""

    auto: PromptCompletionAutoMode = "soft"
    debounce_ms: int = 90
    auto_file_paths: bool = False
    auto_xprompt_menu: bool = True
    auto_directive_menu: bool = True
    auto_artifact_menu: bool = True
    max_auto_rows: int = 1
    history_word_count: int = 10000
    common_placeholder_count: int = 100
    word_min_length: int = 5
    word_ranking: WordRankingMode = "smart"
    word_ranking_signals: bool = True
    placeholder_ranking: PlaceholderRankingMode = "smart"
    placeholder_ranking_signals: bool = True


@dataclass(frozen=True, slots=True)
class PromptSoftCompletion:
    """A single non-disruptive prompt completion suggestion."""

    candidate: CompletionCandidate
    completion_kind: str
    replacement_start: int
    replacement_end: int
    replacement_token: str
    display: str


DEFAULT_PROMPT_COMPLETION_SETTINGS = PromptCompletionSettings()


@dataclass(frozen=True, slots=True)
class PromptSpellcheckSettings:
    """Parsed sticky-misspelling-highlight settings for the TUI prompt bar."""

    highlight: bool = True
    max_remembered_words: int = 5000


DEFAULT_PROMPT_SPELLCHECK_SETTINGS = PromptSpellcheckSettings()


def parse_prompt_spellcheck_settings(raw: Any) -> PromptSpellcheckSettings:
    """Parse ``ace.prompt_spellcheck`` with conservative fallbacks."""
    if not isinstance(raw, dict):
        raw = {}

    highlight = bool(raw.get("highlight", DEFAULT_PROMPT_SPELLCHECK_SETTINGS.highlight))
    max_remembered_words = _parse_non_negative_int(
        raw.get(
            "max_remembered_words",
            DEFAULT_PROMPT_SPELLCHECK_SETTINGS.max_remembered_words,
        ),
        DEFAULT_PROMPT_SPELLCHECK_SETTINGS.max_remembered_words,
    )
    return PromptSpellcheckSettings(
        highlight=highlight,
        max_remembered_words=max_remembered_words,
    )


def parse_prompt_completion_settings(raw: Any) -> PromptCompletionSettings:
    """Parse ``ace.prompt_completion`` with conservative fallbacks."""
    if not isinstance(raw, dict):
        raw = {}

    auto = _parse_auto_mode(raw.get("auto", "soft"))
    debounce_ms = _parse_non_negative_int(
        raw.get("debounce_ms", DEFAULT_PROMPT_COMPLETION_SETTINGS.debounce_ms),
        DEFAULT_PROMPT_COMPLETION_SETTINGS.debounce_ms,
    )
    auto_file_paths = bool(raw.get("auto_file_paths", False))
    auto_xprompt_menu = bool(
        raw.get(
            "auto_xprompt_menu",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.auto_xprompt_menu,
        )
    )
    auto_directive_menu = bool(
        raw.get(
            "auto_directive_menu",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.auto_directive_menu,
        )
    )
    auto_artifact_menu = bool(
        raw.get(
            "auto_artifact_menu",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.auto_artifact_menu,
        )
    )
    max_auto_rows = max(
        1,
        _parse_non_negative_int(
            raw.get("max_auto_rows", DEFAULT_PROMPT_COMPLETION_SETTINGS.max_auto_rows),
            DEFAULT_PROMPT_COMPLETION_SETTINGS.max_auto_rows,
        ),
    )
    history_word_count = _parse_non_negative_int(
        raw.get(
            "history_word_count",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.history_word_count,
        ),
        DEFAULT_PROMPT_COMPLETION_SETTINGS.history_word_count,
    )
    common_placeholder_count = _parse_non_negative_int(
        raw.get(
            "common_placeholder_count",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.common_placeholder_count,
        ),
        DEFAULT_PROMPT_COMPLETION_SETTINGS.common_placeholder_count,
    )
    word_min_length = max(
        1,
        _parse_non_negative_int(
            raw.get(
                "word_min_length",
                DEFAULT_PROMPT_COMPLETION_SETTINGS.word_min_length,
            ),
            DEFAULT_PROMPT_COMPLETION_SETTINGS.word_min_length,
        ),
    )
    word_ranking = _parse_ranking_mode(
        raw.get("word_ranking", DEFAULT_PROMPT_COMPLETION_SETTINGS.word_ranking),
        default=DEFAULT_PROMPT_COMPLETION_SETTINGS.word_ranking,
    )
    word_ranking_signals = bool(
        raw.get(
            "word_ranking_signals",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.word_ranking_signals,
        )
    )
    placeholder_ranking = _parse_ranking_mode(
        raw.get(
            "placeholder_ranking",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.placeholder_ranking,
        ),
        default=DEFAULT_PROMPT_COMPLETION_SETTINGS.placeholder_ranking,
    )
    placeholder_ranking_signals = bool(
        raw.get(
            "placeholder_ranking_signals",
            DEFAULT_PROMPT_COMPLETION_SETTINGS.placeholder_ranking_signals,
        )
    )
    return PromptCompletionSettings(
        auto=auto,
        debounce_ms=debounce_ms,
        auto_file_paths=auto_file_paths,
        auto_xprompt_menu=auto_xprompt_menu,
        auto_directive_menu=auto_directive_menu,
        auto_artifact_menu=auto_artifact_menu,
        max_auto_rows=max_auto_rows,
        history_word_count=history_word_count,
        common_placeholder_count=common_placeholder_count,
        word_min_length=word_min_length,
        word_ranking=word_ranking,
        word_ranking_signals=word_ranking_signals,
        placeholder_ranking=placeholder_ranking,
        placeholder_ranking_signals=placeholder_ranking_signals,
    )


def build_prompt_soft_completion(
    *,
    text: str,
    cursor_offset: int,
    settings: PromptCompletionSettings,
    xprompt_entries: list[XPromptAssistEntry] | None,
    base_dir: str | None = None,
) -> PromptSoftCompletion | None:
    """Build the best warm soft completion at ``cursor_offset``."""
    if settings.auto != "soft":
        return None
    if cursor_offset < 0 or cursor_offset > len(text):
        return None

    jinja_result = build_jinja_completion_result(text, cursor_offset)
    if jinja_result is not None:
        candidate = _first_candidate_that_changes(
            jinja_result.candidates,
            jinja_result.prefix,
        )
        if candidate is not None:
            return PromptSoftCompletion(
                candidate=candidate,
                completion_kind="jinja",
                replacement_start=jinja_result.replacement_start,
                replacement_end=jinja_result.replacement_end,
                replacement_token=text[
                    jinja_result.replacement_start : jinja_result.replacement_end
                ],
                display=candidate.display,
            )

    if xprompt_entries is not None and "#" in text:
        arg_suggestion = _build_xprompt_arg_suggestion(
            text,
            cursor_offset,
            xprompt_entries,
            auto_file_paths=settings.auto_file_paths,
            base_dir=base_dir,
        )
        if arg_suggestion is not None:
            return arg_suggestion

    line_start = text.rfind("\n", 0, cursor_offset) + 1
    line_end = text.find("\n", cursor_offset)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    col = cursor_offset - line_start

    directive_ctx = extract_directive_token_around_cursor(line, col)
    if directive_ctx is not None:
        start, end, token = directive_ctx
        candidates, _shared = build_directive_completion_candidates(token)
        candidate = _first_candidate_that_changes(candidates, token)
        if candidate is not None:
            return _line_suggestion(
                candidate,
                "directive",
                line_start,
                start,
                end,
                token,
            )

    xprompt_span = extract_xprompt_token_around_cursor(line, col)
    if xprompt_span is not None and xprompt_entries is not None:
        candidates, _shared = build_xprompt_completion_candidates(
            xprompt_span.token,
            entries=xprompt_entries,
            inline_reference_only=xprompt_span.clamped,
        )
        candidate = _first_xprompt_soft_candidate(candidates, xprompt_span.token)
        if candidate is not None:
            return _line_suggestion(
                candidate,
                "xprompt",
                line_start,
                xprompt_span.start,
                xprompt_span.end,
                xprompt_span.token,
            )

    token_ctx = extract_token_around_cursor(line, col)
    if token_ctx is None:
        return None
    start, end, token = token_ctx

    if settings.auto_file_paths and is_path_like_token(token):
        candidates, _shared = build_completion_candidates(token, base_dir=base_dir)
        candidate = _first_candidate_that_changes(candidates, token)
        if candidate is not None:
            return _line_suggestion(
                candidate,
                "file",
                line_start,
                start,
                end,
                token,
            )

    return None


def _build_xprompt_arg_suggestion(
    text: str,
    cursor_offset: int,
    entries: list[XPromptAssistEntry],
    *,
    auto_file_paths: bool,
    base_dir: str | None,
) -> PromptSoftCompletion | None:
    ctx = detect_xprompt_arg_completion_at_cursor(text, cursor_offset, entries)
    if ctx is None:
        return None
    if ctx.completion_kind == "xprompt_arg_path" and not auto_file_paths:
        return None
    candidates, _shared = build_xprompt_arg_completion_candidates(
        ctx,
        base_dir=base_dir,
    )
    token = effective_xprompt_arg_token(ctx)
    candidate = _first_candidate_that_changes(candidates, token)
    if candidate is None:
        return None
    return PromptSoftCompletion(
        candidate=candidate,
        completion_kind=ctx.completion_kind,
        replacement_start=ctx.value_start,
        replacement_end=ctx.value_end,
        replacement_token=text[ctx.value_start : ctx.value_end],
        display=candidate.display,
    )


def _line_suggestion(
    candidate: CompletionCandidate,
    completion_kind: str,
    line_start: int,
    start: int,
    end: int,
    token: str,
) -> PromptSoftCompletion:
    return PromptSoftCompletion(
        candidate=candidate,
        completion_kind=completion_kind,
        replacement_start=line_start + start,
        replacement_end=line_start + end,
        replacement_token=token,
        display=candidate.display,
    )


def _first_candidate_that_changes(
    candidates: list[CompletionCandidate],
    token: str,
) -> CompletionCandidate | None:
    for candidate in candidates:
        if candidate.insertion != token:
            return candidate
    return None


def _first_xprompt_soft_candidate(
    candidates: list[CompletionCandidate],
    token: str,
) -> CompletionCandidate | None:
    for candidate in candidates:
        if candidate.insertion != token:
            return candidate
        if candidate.insertion.startswith("#"):
            return candidate
    return None


def _parse_auto_mode(value: Any) -> PromptCompletionAutoMode:
    if isinstance(value, bool):
        return "soft" if value else "off"
    if value is None:
        return "off"
    normalized = str(value).strip().lower()
    if normalized in {"0", "false", "no", "off", "none", "disabled"}:
        return "off"
    if normalized in {"1", "true", "yes", "on", "soft"}:
        return "soft"
    return DEFAULT_PROMPT_COMPLETION_SETTINGS.auto


def _parse_ranking_mode(value: Any, *, default: WordRankingMode) -> WordRankingMode:
    normalized = str(value).strip().lower()
    if normalized == "recent":
        return "recent"
    if normalized == "smart":
        return "smart"
    return default


def _parse_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)

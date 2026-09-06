"""Jinja2 completion candidates for the prompt input bar."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt import jinja_inspect


@dataclass(frozen=True, slots=True)
class JinjaCompletionMetadata:
    """Display metadata for a Jinja2 completion candidate."""

    kind: str


@dataclass(frozen=True, slots=True)
class JinjaCompletionResult:
    """Completion context plus candidates for a Jinja2 tag."""

    prefix: str
    replacement_start: int
    replacement_end: int
    candidates: list[CompletionCandidate]
    shared_extension: str


def build_jinja_completion_result(
    text: str,
    cursor_offset: int,
) -> JinjaCompletionResult | None:
    """Return Jinja2 completions at *cursor_offset*, if the cursor is in a tag."""
    ctx = jinja_inspect.completion_context(text, cursor_offset)
    if ctx is None:
        return None

    candidates = _candidates_for_prefix(
        ctx.prefix,
        tag_kind=ctx.tag_kind,
        namespace=ctx.namespace,
    )
    if not candidates:
        return JinjaCompletionResult(
            prefix=ctx.prefix,
            replacement_start=ctx.replacement_start,
            replacement_end=ctx.replacement_end,
            candidates=[],
            shared_extension="",
        )

    shared_extension = _shared_extension(
        [candidate.insertion for candidate in candidates],
        ctx.prefix,
    )
    return JinjaCompletionResult(
        prefix=ctx.prefix,
        replacement_start=ctx.replacement_start,
        replacement_end=ctx.replacement_end,
        candidates=candidates,
        shared_extension=shared_extension,
    )


def _candidates_for_prefix(
    prefix: str,
    *,
    tag_kind: str,
    namespace: str | None,
) -> list[CompletionCandidate]:
    prefix_lower = prefix.lower()
    if namespace is not None:
        return _rows(
            sorted(jinja_inspect.builtin_runtime_member_names(namespace)),
            "variable",
            prefix_lower,
        )

    variables = sorted(
        jinja_inspect.known_toplevel_context() | jinja_inspect.builtin_runtime_names()
    )
    keywords = sorted(jinja_inspect.JINJA_KEYWORDS)
    filters = list(jinja_inspect.jinja_filter_names())

    rows: list[CompletionCandidate] = []
    if tag_kind == "block":
        rows.extend(_rows(keywords, "keyword", prefix_lower))
        rows.extend(_rows(variables, "variable", prefix_lower))
    else:
        rows.extend(_rows(variables, "variable", prefix_lower))
        rows.extend(_rows(filters, "filter", prefix_lower))
        rows.extend(_rows(keywords, "keyword", prefix_lower))

    return rows


def _rows(
    names: list[str],
    kind: str,
    prefix_lower: str,
) -> list[CompletionCandidate]:
    rows: list[CompletionCandidate] = []
    for name in names:
        if prefix_lower and not name.lower().startswith(prefix_lower):
            continue
        rows.append(
            CompletionCandidate(
                display=name,
                insertion=name,
                is_dir=False,
                name=name,
                metadata=JinjaCompletionMetadata(kind),
            )
        )
    return rows


def _shared_extension(insertions: list[str], prefix: str) -> str:
    if len(insertions) <= 1:
        return ""
    shared = insertions[0]
    for insertion in insertions[1:]:
        max_len = min(len(shared), len(insertion))
        idx = 0
        while idx < max_len and shared[idx].lower() == insertion[idx].lower():
            idx += 1
        shared = shared[:idx]
        if not shared:
            return ""
    if len(shared) <= len(prefix):
        return ""
    return shared[len(prefix) :]

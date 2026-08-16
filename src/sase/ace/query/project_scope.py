"""Token-preserving Patch project-scope query rewrites."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .highlighting import tokenize_query_for_display

PROJECT_SCOPE_NESTED: Final = "__SASE_PROJECT_SCOPE_NESTED__"


@dataclass(frozen=True, slots=True)
class _Span:
    token: str
    kind: str
    start: int
    end: int
    depth: int


@dataclass(frozen=True, slots=True)
class _ProjectTerm:
    value: str
    spelling: str
    start: int
    end: int
    token_start: int
    token_end: int
    value_start: int
    value_end: int


def project_scope_of(query: str) -> str | None:
    """Return the first top-level Patch project scope in *query*, if any."""

    terms, _nested = _project_terms(query)
    return terms[0].value if terms else None


def rewrite_project_scope(query: str, project: str | None) -> str:
    """Return *query* with only its top-level Patch project scope rewritten."""

    terms, nested = _project_terms(query)
    if not terms:
        if nested:
            return PROJECT_SCOPE_NESTED
        if project is None:
            return query
        return _append_project_scope(query, project)

    edits: list[tuple[int, int, str]] = []
    first = terms[0]
    if project is None:
        edits.append((*_removal_range(_spans(query), first), ""))
    elif first.spelling == "sigil":
        edits.append((first.start, first.end, f"+{project}"))
    else:
        edits.append((first.value_start, first.value_end, project))

    spans = _spans(query)
    for term in terms[1:]:
        edits.append((*_removal_range(spans, term), ""))
    return _apply_edits(query, edits)


def _project_terms(query: str) -> tuple[list[_ProjectTerm], bool]:
    spans = _spans(query)
    terms: list[_ProjectTerm] = []
    nested = False
    index = 0
    while index < len(spans):
        span = spans[index]
        term: _ProjectTerm | None = None
        if span.kind == "shorthand" and span.token.startswith("+"):
            term = _ProjectTerm(
                value=span.token[1:],
                spelling="sigil",
                start=span.start,
                end=span.end,
                token_start=index,
                token_end=index,
                value_start=span.start + 1,
                value_end=span.end,
            )
        elif span.kind == "property_key" and span.token.casefold() == "project:":
            value_index = _next_non_whitespace(spans, index + 1)
            if value_index is not None and spans[value_index].kind == "property_value":
                value_span = spans[value_index]
                term = _ProjectTerm(
                    value=_unquote_value(value_span.token),
                    spelling="property",
                    start=span.start,
                    end=value_span.end,
                    token_start=index,
                    token_end=value_index,
                    value_start=value_span.start,
                    value_end=value_span.end,
                )
        if term is not None:
            if span.depth == 0:
                terms.append(term)
            else:
                nested = True
            index = term.token_end + 1
            continue
        index += 1
    return terms, nested


def _spans(query: str) -> list[_Span]:
    spans: list[_Span] = []
    offset = 0
    depth = 0
    for token, kind in tokenize_query_for_display(query):
        start = offset
        end = start + len(token)
        token_depth = depth
        if kind == "paren" and token == ")":
            depth = max(0, depth - 1)
            token_depth = depth
        spans.append(_Span(token, kind, start, end, token_depth))
        if kind == "paren" and token == "(":
            depth += 1
        offset = end
    return spans


def _removal_range(spans: list[_Span], term: _ProjectTerm) -> tuple[int, int]:
    prev_index = _prev_non_whitespace(spans, term.token_start - 1)
    next_index = _next_non_whitespace(spans, term.token_end + 1)
    if prev_index is not None and _is_and(spans[prev_index]):
        prev_prev = _prev_non_whitespace(spans, prev_index - 1)
        start = (
            spans[prev_prev].end if prev_prev is not None else spans[prev_index].start
        )
        return (start, term.end)
    if next_index is not None and _is_and(spans[next_index]):
        next_next = _next_non_whitespace(spans, next_index + 1)
        end = spans[next_next].start if next_next is not None else spans[next_index].end
        return (term.start, end)
    start = spans[prev_index].end if prev_index is not None else term.start
    end = spans[next_index].start if next_index is not None else term.end
    return (start, end)


def _is_and(span: _Span) -> bool:
    return span.kind == "keyword" and span.token.casefold() == "and"


def _next_non_whitespace(spans: list[_Span], index: int) -> int | None:
    while index < len(spans):
        if spans[index].kind != "whitespace":
            return index
        index += 1
    return None


def _prev_non_whitespace(spans: list[_Span], index: int) -> int | None:
    while index >= 0:
        if spans[index].kind != "whitespace":
            return index
        index -= 1
    return None


def _append_project_scope(query: str, project: str) -> str:
    if not query.strip():
        return f"project:{project}"
    separator = "AND " if query.endswith(tuple(" \t\r\n")) else " AND "
    return f"{query}{separator}project:{project}"


def _apply_edits(query: str, edits: list[tuple[int, int, str]]) -> str:
    if not edits:
        return query
    normalized = sorted(edits, key=lambda item: item[0])
    pieces: list[str] = []
    cursor = 0
    for start, end, replacement in normalized:
        if start < cursor:
            continue
        pieces.append(query[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(query[cursor:])
    return "".join(pieces)


def _unquote_value(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


__all__ = ["PROJECT_SCOPE_NESTED", "project_scope_of", "rewrite_project_scope"]

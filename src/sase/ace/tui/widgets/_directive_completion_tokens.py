"""Token extraction helpers for prompt directive completion.

Classification and replacement ranges come from the shared
``sase_core_rs`` grammar. ACE only maps UTF-16 positions, rejects
non-directive ``%`` contexts, and keeps wait-prose commas from opening
a completion menu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

from sase.ace.tui.util.editor_offsets import editor_range_to_offsets, utf16_character
from sase.core.rust import require_rust_binding

_DIRECTIVE_TOKEN_RE = re.compile(r"^%[A-Za-z0-9_]*$")
_DIRECTIVE_OPENING_CONTEXTS = frozenset("([{\"'")

DirectiveCompletionKind = Literal[
    "directive_name",
    "directive_argument",
    "directive_argument_keyword",
    "directive_argument_value",
]


@dataclass(frozen=True, slots=True)
class DirectiveClauseCompletion:
    """ACE-facing classification of the directive clause at the cursor."""

    kind: DirectiveCompletionKind
    token: str
    start: int
    end: int
    directive_name: str | None
    syntax_form: str | None
    clause_kind: str | None
    active_keyword: str | None
    value_role: str | None
    selected_values: tuple[str, ...]
    selected_keywords: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def is_name(self) -> bool:
        return self.kind == "directive_name"

    @property
    def is_keyword_value(self) -> bool:
        return self.kind == "directive_argument_value"

    @property
    def is_wait_positional(self) -> bool:
        return (
            self.directive_name == "wait"
            and not self.is_keyword_value
            and self.value_role != "bead"
        )


def is_directive_like_token(token: str) -> bool:
    """Return True when token looks like a prompt directive reference."""
    return _DIRECTIVE_TOKEN_RE.fullmatch(token) is not None


def classify_directive_completion(
    line: str,
    col: int,
) -> DirectiveClauseCompletion | None:
    """Classify the directive clause at a Python character offset.

    *line* is treated as a one-line document so replacement columns stay
    row-local for the prompt widget.
    """
    col = min(max(col, 0), len(line))
    percent_index = line.rfind("%", 0, col if col > 0 else 0)
    if percent_index < 0 or not _has_valid_directive_context(line, percent_index):
        return None

    payload = require_rust_binding("directive_completion_context")(
        line,
        0,
        utf16_character(line[:col]),
    )
    if not isinstance(payload, dict):
        return None

    kind = payload.get("kind")
    if kind not in {
        "directive_name",
        "directive_argument",
        "directive_argument_keyword",
        "directive_argument_value",
    }:
        return None

    token_info = payload.get("token")
    token = ""
    if isinstance(token_info, dict):
        token = str(token_info.get("text") or "")

    if kind == "directive_name" and not is_directive_like_token(token):
        return None

    replacement = editor_range_to_offsets(
        line,
        payload.get("replacement_range"),
        allow_empty=True,
    )
    if replacement is None:
        token_range = (
            editor_range_to_offsets(
                line,
                token_info.get("range") if isinstance(token_info, dict) else None,
                allow_empty=True,
            )
            if isinstance(token_info, dict)
            else None
        )
        if token_range is None:
            return None
        start, end = token_range
    else:
        start, end = replacement

    directive = payload.get("directive")
    directive_fields = directive if isinstance(directive, dict) else {}
    selected_values = _string_tuple(payload.get("selected_values"))
    selected_keywords = _string_tuple(directive_fields.get("selected_keywords"))
    raw_name = payload.get("directive_name")
    canonical = (
        _canonical_directive_name(str(raw_name)) if isinstance(raw_name, str) else None
    )
    if canonical is None and isinstance(raw_name, str) and raw_name:
        canonical = raw_name
    clause = DirectiveClauseCompletion(
        kind=kind,
        token=token,
        start=start,
        end=end,
        directive_name=canonical,
        syntax_form=_optional_str(directive_fields.get("syntax_form")),
        clause_kind=_optional_str(directive_fields.get("clause_kind")),
        active_keyword=_optional_str(directive_fields.get("active_keyword")),
        value_role=_optional_str(directive_fields.get("value_role")),
        selected_values=selected_values,
        selected_keywords=selected_keywords,
        raw=payload,
    )
    if clause.directive_name == "wait" and not _wait_fragments_are_structured(clause):
        return None
    if not _colon_argument_chars_are_valid(clause):
        return None
    return clause


def extract_directive_token_around_cursor(
    line: str,
    col: int,
) -> tuple[int, int, str] | None:
    """Extract a directive token around a cursor position in one line."""
    clause = classify_directive_completion(line, col)
    if clause is None or not clause.is_name:
        return None
    return clause.start, clause.end, clause.token


def extract_directive_arg_token_around_cursor(
    line: str,
    col: int,
) -> tuple[int, int, str, str] | None:
    """Extract a directive argument token around the cursor.

    Returns ``(arg_start, arg_end, directive_name, partial)``. Keyword-name
    contexts keep the historical ``clan_keyword`` / ``id_keyword`` /
    ``model_alias_key`` / ``model_or_alias_key`` labels so existing callers
    can dispatch without the full clause object.
    """
    clause = classify_directive_completion(line, col)
    if clause is None or clause.is_name:
        return None
    return clause.start, clause.end, compat_directive_name(clause), clause.token


def selected_wait_values_around_cursor(
    line: str,
    active_start: int,
) -> frozenset[str]:
    """Return completed ``%wait`` values outside the active comma clause."""
    clause = classify_directive_completion(line, min(max(active_start, 0), len(line)))
    if clause is None or clause.directive_name != "wait":
        return frozenset()
    return frozenset(clause.selected_values)


def _canonical_directive_name(raw_name: str) -> str | None:
    """Resolve a directive alias to a known canonical name."""
    return _contract_aliases().get(raw_name)


def compat_directive_name(clause: DirectiveClauseCompletion) -> str:
    """Return the historical argument-dispatch name for *clause*."""
    name = clause.directive_name or ""
    if clause.kind == "directive_argument_keyword":
        if name == "clan":
            return "clan_keyword"
        if name == "id":
            return "id_keyword"
        if name == "model":
            return "model_alias_key"
    if (
        name == "model"
        and clause.syntax_form == "parenthesized"
        and clause.clause_kind == "positional"
        and clause.kind == "directive_argument"
    ):
        return "model_or_alias_key"
    return name


def synthetic_directive_clause(
    *,
    kind: DirectiveCompletionKind,
    token: str,
    directive_name: str | None,
    syntax_form: str | None = None,
    clause_kind: str | None = None,
    active_keyword: str | None = None,
    value_role: str | None = None,
    selected_values: frozenset[str] | tuple[str, ...] = (),
    selected_keywords: frozenset[str] | tuple[str, ...] = (),
) -> DirectiveClauseCompletion:
    """Build a clause object for tests and the argument-name convenience API."""
    selected_value_tuple = tuple(selected_values)
    selected_keyword_tuple = tuple(selected_keywords)
    token_range = {
        "start": {"line": 0, "character": 0},
        "end": {"line": 0, "character": utf16_character(token)},
    }
    raw: dict[str, Any] = {
        "kind": kind,
        "token": {
            "text": token,
            "range": token_range,
            "byte_start": 0,
            "byte_end": len(token),
        },
        "directive_name": directive_name,
        "selected_values": list(selected_value_tuple),
        "replacement_range": token_range,
    }
    if (
        syntax_form is not None
        or clause_kind is not None
        or active_keyword is not None
        or value_role is not None
        or selected_keyword_tuple
    ):
        directive: dict[str, Any] = {
            "syntax_form": syntax_form or "colon",
            "clause_kind": clause_kind or "positional",
            "selected_keywords": list(selected_keyword_tuple),
        }
        if active_keyword is not None:
            directive["active_keyword"] = active_keyword
        if value_role is not None:
            directive["value_role"] = value_role
        raw["directive"] = directive
    return DirectiveClauseCompletion(
        kind=kind,
        token=token,
        start=0,
        end=len(token),
        directive_name=directive_name,
        syntax_form=syntax_form,
        clause_kind=clause_kind,
        active_keyword=active_keyword,
        value_role=value_role,
        selected_values=selected_value_tuple,
        selected_keywords=selected_keyword_tuple,
        raw=raw,
    )


@cache
def _contract_aliases() -> dict[str, str]:
    mapping: dict[str, str] = {"(": "alt", "{": "alt"}
    for entry in require_rust_binding("directive_contract")():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        mapping[name] = name
        alias = entry.get("alias")
        if isinstance(alias, str) and alias:
            mapping[alias] = name
    return mapping


def _has_valid_directive_context(line: str, percent_index: int) -> bool:
    if percent_index == 0:
        return True
    previous = line[percent_index - 1]
    return previous.isspace() or previous in _DIRECTIVE_OPENING_CONTEXTS


def _wait_fragments_are_structured(clause: DirectiveClauseCompletion) -> bool:
    """Return False when wait completion would attach to surrounding prose."""
    fragments = (*clause.selected_values, clause.token)
    return all(_wait_fragment_is_structured(fragment) for fragment in fragments)


def _colon_argument_chars_are_valid(clause: DirectiveClauseCompletion) -> bool:
    """Keep colon-form typing from attaching to trailing prose or punctuation."""
    if clause.is_name or clause.syntax_form != "colon":
        return True
    if clause.directive_name == "wait":
        return True
    extra = "-="
    if clause.directive_name == "model" or clause.value_role == "model":
        extra = "-=./@"
    return all(char.isalnum() or char == "_" or char in extra for char in clause.token)


def _wait_fragment_is_structured(fragment: str) -> bool:
    stripped = fragment.strip()
    if not stripped:
        return True
    if stripped[0] in "\"'`" or stripped.startswith("[["):
        return True
    return " " not in stripped and "\t" not in stripped


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None

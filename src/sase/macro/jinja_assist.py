"""Typed facade over the Rust Jinja completion engine.

The tag detection, catalog, scope analysis, ranking, and documentation live
in ``sase-core`` and are shared with the macro LSP. This module only
rehydrates the binding's JSON-shaped values so callers do not depend on
untyped dictionaries, converting Python character offsets to the LSP
UTF-16 positions the engine expects (the same way the placeholder
completion widget does).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Literal

from sase.core.rust import require_rust_binding

JinjaScopeKind = Literal["prompt", "xprompt"]
JinjaCompletionSlot = Literal[
    "variable", "member", "filter", "test", "statement", "none"
]
JinjaCompletionItemKind = Literal[
    "variable", "member", "function", "filter", "test", "keyword"
]
JinjaCompletionSource = Literal[
    "input", "local", "sase", "positional", "provider", "jinja"
]
JinjaAvailabilityState = Literal["available", "conditional"]


@dataclass(frozen=True, slots=True)
class JinjaScope:
    """Document scope a Jinja assist request runs in.

    ``prompt`` is a top-level agent prompt; ``macro`` is a macro
    definition body. ``frontmatter`` carries the pane's lifted (stack)
    frontmatter YAML; the engine also reads the in-text leading
    frontmatter block itself.
    """

    kind: JinjaScopeKind
    frontmatter: str | None = None


@dataclass(frozen=True, slots=True)
class _JinjaPosition:
    """Zero-based LSP position whose character offset is measured in UTF-16."""

    line: int
    character: int


@dataclass(frozen=True, slots=True)
class JinjaAvailability:
    """Whether a candidate renders in the current scope."""

    state: JinjaAvailabilityState
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class JinjaCompletionItem:
    """One ranked completion candidate."""

    name: str
    insertion: str
    kind: JinjaCompletionItemKind
    source: JinjaCompletionSource
    type_label: str | None = None
    signature: str | None = None
    summary: str | None = None
    documentation: str = ""
    required: bool = False
    default_display: str | None = None
    choices: tuple[str, ...] = ()
    availability: JinjaAvailability = field(
        default_factory=lambda: JinjaAvailability(state="available")
    )
    legacy_for: str | None = None
    closes: str | None = None
    shadows: str | None = None
    match_runs: tuple[tuple[int, int], ...] = ()
    rank: int = 0


@dataclass(frozen=True, slots=True)
class JinjaCompletion:
    """Ranked completion response for one cursor."""

    slot: JinjaCompletionSlot
    namespace: str | None
    prefix: str
    replacement_start: int
    replacement_end: int
    items: tuple[JinjaCompletionItem, ...]
    shared_extension: str = ""


@dataclass(frozen=True, slots=True)
class JinjaUnavailableVariable:
    """One name that would fail in the current scope, with its reason."""

    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class JinjaScopeVariables:
    """Scope-variable list backing the unknown-variable lint."""

    known: tuple[str, ...] = ()
    positional_pattern: bool = False
    unavailable: tuple[JinjaUnavailableVariable, ...] = ()


@dataclass(frozen=True, slots=True)
class JinjaCatalogMember:
    """One member of a namespace variable such as ``wait``."""

    name: str
    type_label: str = ""
    summary: str = ""


@dataclass(frozen=True, slots=True)
class JinjaCatalogVariable:
    """One sase-injected variable in the static catalog."""

    name: str
    type_label: str = ""
    group: JinjaCompletionSource = "sase"
    summary: str = ""
    documentation: str = ""
    availability_rule: str = "always"
    legacy_for: str | None = None
    members: tuple[JinjaCatalogMember, ...] = ()


@dataclass(frozen=True, slots=True)
class JinjaCatalogFilter:
    """One filter in the static catalog."""

    name: str
    signature: str = ""
    summary: str = ""
    tier: str = "other"


@dataclass(frozen=True, slots=True)
class JinjaCatalogTest:
    """One test in the static catalog."""

    name: str
    summary: str = ""


@dataclass(frozen=True, slots=True)
class JinjaCatalogGlobal:
    """One Jinja global in the static catalog."""

    name: str
    signature: str = ""
    summary: str = ""


@dataclass(frozen=True, slots=True)
class JinjaCatalogStatement:
    """One statement keyword in the static catalog."""

    name: str
    closer: str | None = None
    summary: str = ""


@dataclass(frozen=True, slots=True)
class JinjaCatalog:
    """Static Jinja catalog: variables, filters, tests, globals, statements."""

    variables: tuple[JinjaCatalogVariable, ...] = ()
    filters: tuple[JinjaCatalogFilter, ...] = ()
    tests: tuple[JinjaCatalogTest, ...] = ()
    jinja_globals: tuple[JinjaCatalogGlobal, ...] = ()
    statements: tuple[JinjaCatalogStatement, ...] = ()


def jinja_completion(
    text: str,
    cursor_offset: int,
    scope: JinjaScope,
) -> JinjaCompletion | None:
    """Return ranked Jinja completion at *cursor_offset*, if inside a tag.

    Returns ``None`` when the cursor is outside any Jinja tag (or the
    offset is out of range); an in-tag position with no candidates yields
    a completion with empty items.
    """
    binding = require_rust_binding("jinja_completion")
    position = _position_for_offset(text, cursor_offset)
    if position is None:
        return None
    payload = binding(
        {
            "text": text,
            "position": {"line": position.line, "character": position.character},
            "scope": scope.kind,
            "frontmatter": scope.frontmatter,
        }
    )
    if payload is None:
        return None
    return _completion_from_dict(text, payload)


def jinja_scope_variables(text: str, scope: JinjaScope) -> JinjaScopeVariables:
    """Return the scope-variable list backing the unknown-variable lint."""
    binding = require_rust_binding("jinja_scope_variables")
    payload = binding(
        {"text": text, "scope": scope.kind, "frontmatter": scope.frontmatter}
    )
    return _scope_variables_from_dict(payload)


@functools.cache
def jinja_catalog() -> JinjaCatalog:
    """Return the static Jinja catalog shared with the LSP."""
    binding = require_rust_binding("jinja_catalog")
    return _catalog_from_dict(binding())


def _completion_from_dict(text: str, payload: dict[str, Any]) -> JinjaCompletion | None:
    replacement = _offsets_for_range(text, payload.get("replacement_range"))
    if replacement is None:
        return None
    replacement_start, replacement_end = replacement
    return JinjaCompletion(
        slot=_slot_from_value(payload.get("slot")),
        namespace=_optional_str(payload.get("namespace")),
        prefix=str(payload.get("prefix", "")),
        replacement_start=replacement_start,
        replacement_end=replacement_end,
        items=tuple(_item_from_dict(item) for item in payload.get("items", []) or []),
        shared_extension=str(payload.get("shared_extension", "")),
    )


def _item_from_dict(payload: dict[str, Any]) -> JinjaCompletionItem:
    availability = payload.get("availability") or {}
    return JinjaCompletionItem(
        name=str(payload.get("name", "")),
        insertion=str(payload.get("insertion", payload.get("name", ""))),
        kind=_kind_from_value(payload.get("kind")),
        source=_source_from_value(payload.get("source")),
        type_label=_optional_str(payload.get("type_label")),
        signature=_optional_str(payload.get("signature")),
        summary=_optional_str(payload.get("summary")),
        documentation=str(payload.get("documentation", "")),
        required=bool(payload.get("required", False)),
        default_display=_optional_str(payload.get("default_display")),
        choices=tuple(str(choice) for choice in payload.get("choices", []) or []),
        availability=JinjaAvailability(
            state=_state_from_value(availability.get("state")),
            hint=_optional_str(availability.get("hint")),
        ),
        legacy_for=_optional_str(payload.get("legacy_for")),
        closes=_optional_str(payload.get("closes")),
        shadows=_optional_str(payload.get("shadows")),
        match_runs=tuple(
            (int(start), int(end)) for start, end in payload.get("match_runs", []) or []
        ),
        rank=int(payload.get("rank", 0)),
    )


def _scope_variables_from_dict(payload: dict[str, Any]) -> JinjaScopeVariables:
    return JinjaScopeVariables(
        known=tuple(str(name) for name in payload.get("known", []) or []),
        positional_pattern=bool(payload.get("positional_pattern", False)),
        unavailable=tuple(
            JinjaUnavailableVariable(
                name=str(item.get("name", "")),
                reason=str(item.get("reason", "")),
            )
            for item in payload.get("unavailable", []) or []
        ),
    )


def _catalog_from_dict(payload: dict[str, Any]) -> JinjaCatalog:
    return JinjaCatalog(
        variables=tuple(
            JinjaCatalogVariable(
                name=str(item.get("name", "")),
                type_label=str(item.get("type_label", "")),
                group=_source_from_value(item.get("group")),
                summary=str(item.get("summary", "")),
                documentation=str(item.get("documentation", "")),
                availability_rule=str(item.get("availability_rule", "always")),
                legacy_for=_optional_str(item.get("legacy_for")),
                members=tuple(
                    JinjaCatalogMember(
                        name=str(member.get("name", "")),
                        type_label=str(member.get("type_label", "")),
                        summary=str(member.get("summary", "")),
                    )
                    for member in item.get("members", []) or []
                ),
            )
            for item in payload.get("variables", []) or []
        ),
        filters=tuple(
            JinjaCatalogFilter(
                name=str(item.get("name", "")),
                signature=str(item.get("signature", "")),
                summary=str(item.get("summary", "")),
                tier=str(item.get("tier", "other")),
            )
            for item in payload.get("filters", []) or []
        ),
        tests=tuple(
            JinjaCatalogTest(
                name=str(item.get("name", "")),
                summary=str(item.get("summary", "")),
            )
            for item in payload.get("tests", []) or []
        ),
        jinja_globals=tuple(
            JinjaCatalogGlobal(
                name=str(item.get("name", "")),
                signature=str(item.get("signature", "")),
                summary=str(item.get("summary", "")),
            )
            for item in payload.get("jinja_globals", []) or []
        ),
        statements=tuple(
            JinjaCatalogStatement(
                name=str(item.get("name", "")),
                closer=_optional_str(item.get("closer")),
                summary=str(item.get("summary", "")),
            )
            for item in payload.get("statements", []) or []
        ),
    )


def _slot_from_value(value: Any) -> JinjaCompletionSlot:
    # An unrecognised slot degrades to ``none`` (no menu) rather than
    # raising: a newer core adding a slot must never break this menu.
    slot = str(value) if value is not None else "none"
    if slot in ("variable", "member", "filter", "test", "statement", "none"):
        return slot  # type: ignore[return-value]
    return "none"


def _kind_from_value(value: Any) -> JinjaCompletionItemKind:
    kind = str(value) if value is not None else "variable"
    if kind in ("variable", "member", "function", "filter", "test", "keyword"):
        return kind  # type: ignore[return-value]
    return "variable"


def _source_from_value(value: Any) -> JinjaCompletionSource:
    # An unrecognised source degrades to ``jinja`` rather than raising: a
    # newer core adding a source must never break an older client's menu.
    source = str(value) if value is not None else "jinja"
    if source in ("input", "local", "sase", "positional", "provider", "jinja"):
        return source  # type: ignore[return-value]
    return "jinja"


def _state_from_value(value: Any) -> JinjaAvailabilityState:
    state = str(value) if value is not None else "available"
    if state in ("available", "conditional"):
        return state  # type: ignore[return-value]
    return "available"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _position_for_offset(text: str, offset: int) -> _JinjaPosition | None:
    """Convert a Python character offset to an LSP UTF-16 position."""
    if offset < 0 or offset > len(text):
        return None
    line_start = text.rfind("\n", 0, offset) + 1
    line = text.count("\n", 0, line_start)
    character = sum(_utf16_width(char) for char in text[line_start:offset])
    return _JinjaPosition(line=line, character=character)


def _offsets_for_range(text: str, editor_range: Any) -> tuple[int, int] | None:
    """Convert an LSP UTF-16 range dict to Python character offsets."""
    if not isinstance(editor_range, dict):
        return None
    start = _offset_for_position(text, editor_range.get("start"))
    end = _offset_for_position(text, editor_range.get("end"))
    if start is None or end is None or end < start:
        return None
    return start, end


def _offset_for_position(text: str, position: Any) -> int | None:
    """Convert one UTF-16 ``{line, character}`` position to a Python offset."""
    if not isinstance(position, dict):
        return None
    line = position.get("line")
    character = position.get("character")
    if not isinstance(line, int) or not isinstance(character, int):
        return None
    if line < 0 or character < 0:
        return None
    line_start = 0
    for _ in range(line):
        newline = text.find("\n", line_start)
        if newline == -1:
            return None
        line_start = newline + 1
    offset = line_start
    width = 0
    while offset < len(text) and width < character:
        newline = text.find("\n", line_start)
        line_end = len(text) if newline == -1 else newline
        if offset >= line_end:
            break
        if text[offset] == "\r" and offset + 1 == line_end:
            break
        width += _utf16_width(text[offset])
        offset += 1
    if width != character:
        return None
    return offset


def _utf16_width(char: str) -> int:
    return 2 if ord(char) > 0xFFFF else 1


__all__ = [
    "JinjaAvailability",
    "JinjaAvailabilityState",
    "JinjaCatalog",
    "JinjaCatalogFilter",
    "JinjaCatalogGlobal",
    "JinjaCatalogMember",
    "JinjaCatalogStatement",
    "JinjaCatalogTest",
    "JinjaCatalogVariable",
    "JinjaCompletion",
    "JinjaCompletionItem",
    "JinjaCompletionItemKind",
    "JinjaCompletionSlot",
    "JinjaCompletionSource",
    "JinjaScope",
    "JinjaScopeKind",
    "JinjaScopeVariables",
    "JinjaUnavailableVariable",
    "jinja_catalog",
    "jinja_completion",
    "jinja_scope_variables",
]

"""Boolean parser for profile-driven reference queries."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from sase.ace.query.profile_reference_support import (
    ProfileQueryError,
    and_terms,
    normalize_query_value,
    or_terms,
    require_filterable_field,
)
from sase.ace.query.types import (
    ERROR_SUFFIX_QUERY,
    RUNNING_AGENT_QUERY,
    RUNNING_PROCESS_QUERY,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.ace.query_profile import CompiledQueryProfile

_PROPERTY_VALUE_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


@dataclass(frozen=True, slots=True)
class _ProfileToken:
    kind: Literal[
        "string",
        "property",
        "and",
        "or",
        "not",
        "predicate",
        "not_predicate",
        "any_special",
        "lparen",
        "rparen",
        "eof",
    ]
    value: str
    position: int
    case_sensitive: bool = False
    property_key: str | None = None
    predicate: str | None = None


def parse_boolean_query(query: str, profile: CompiledQueryProfile) -> QueryExpr:
    """Parse a boolean profile query into the shared query AST."""

    return _BooleanProfileParser(query, profile).parse()


class _BooleanProfileParser:
    def __init__(self, query: str, profile: CompiledQueryProfile) -> None:
        self.query = query
        self.profile = profile
        self.tokens = _tokenize_boolean_query(query, profile)
        self.pos = 0

    def _current(self) -> _ProfileToken:
        return self.tokens[self.pos]

    def _advance(self) -> _ProfileToken:
        token = self._current()
        self.pos += 1
        return token

    def _check(self, kind: str) -> bool:
        return self._current().kind == kind

    def _expect(self, kind: str) -> _ProfileToken:
        token = self._current()
        if token.kind != kind:
            raise ProfileQueryError(
                f"Expected {kind}, got {token.kind}", token.position
            )
        return self._advance()

    def parse(self) -> QueryExpr:
        if self._check("eof"):
            raise ProfileQueryError("Empty query", 0)
        expr = self._parse_or_expr()
        if not self._check("eof"):
            token = self._current()
            raise ProfileQueryError(
                f"Unexpected token: {token.value or token.kind}",
                token.position,
            )
        return expr

    def _parse_or_expr(self) -> QueryExpr:
        operands = [self._parse_and_expr()]
        while self._check("or"):
            self._advance()
            operands.append(self._parse_and_expr())
        return or_terms(operands)

    def _parse_and_expr(self) -> QueryExpr:
        operands = [self._parse_unary_expr()]
        while True:
            if self._check("and"):
                self._advance()
                operands.append(self._parse_unary_expr())
            elif self._can_start_unary():
                operands.append(self._parse_unary_expr())
            else:
                break
        return and_terms(operands)

    def _parse_unary_expr(self) -> QueryExpr:
        not_count = 0
        while self._check("not"):
            self._advance()
            not_count += 1
        expr = self._parse_primary()
        for _ in range(not_count):
            expr = NotExpr(expr)
        return expr

    def _parse_primary(self) -> QueryExpr:
        token = self._current()
        if token.kind == "string":
            self._advance()
            return StringMatch(token.value, case_sensitive=token.case_sensitive)
        if token.kind == "property":
            self._advance()
            assert token.property_key is not None
            return PropertyMatch(token.property_key, token.value)
        if token.kind == "predicate":
            self._advance()
            return _predicate_expr(token)
        if token.kind == "not_predicate":
            self._advance()
            return NotExpr(_predicate_expr(token))
        if token.kind == "any_special":
            self._advance()
            return OrExpr(
                [_predicate_expr_for_name(name) for name in self.profile.predicates]
            )
        if token.kind == "lparen":
            self._advance()
            expr = self._parse_or_expr()
            self._expect("rparen")
            return expr
        raise ProfileQueryError(
            f"Expected string or '(', got {token.value or token.kind}",
            token.position,
        )

    def _can_start_unary(self) -> bool:
        return self._current().kind in {
            "string",
            "property",
            "not",
            "predicate",
            "not_predicate",
            "any_special",
            "lparen",
        }


def _tokenize_boolean_query(
    query: str,
    profile: CompiledQueryProfile,
) -> tuple[_ProfileToken, ...]:
    tokens: list[_ProfileToken] = []
    pos = 0
    while pos < len(query):
        while pos < len(query) and query[pos].isspace():
            pos += 1
        if pos >= len(query):
            break
        char = query[pos]
        if char == "c" and pos + 1 < len(query) and query[pos + 1] == '"':
            token, pos = _parse_quoted_string(query, pos + 1, case_sensitive=True)
            tokens.append(token)
        elif char == '"':
            token, pos = _parse_quoted_string(query, pos, case_sensitive=False)
            tokens.append(token)
        elif char == "!":
            token, pos = _parse_bang(query, pos, profile)
            tokens.append(token)
        elif char in {"@", "$"}:
            token, pos = _parse_predicate_sigil(query, pos, profile)
            tokens.append(token)
        elif char == "*":
            if not profile.any_special:
                raise ProfileQueryError("Unexpected character: *", pos)
            if not _standalone_at(query, pos + 1):
                raise ProfileQueryError("Unexpected character: *", pos)
            tokens.append(_ProfileToken("any_special", "*", pos))
            pos += 1
        elif char == "(":
            tokens.append(_ProfileToken("lparen", "(", pos))
            pos += 1
        elif char == ")":
            tokens.append(_ProfileToken("rparen", ")", pos))
            pos += 1
        elif char in {item.trigger for item in profile.macros}:
            token, pos = _parse_macro(query, pos, profile)
            tokens.append(token)
        elif char in {item.sigil for item in profile.sigils}:
            token, pos = _parse_field_sigil(query, pos, profile)
            tokens.append(token)
        elif _is_bare_word_start_char(char):
            token, pos = _parse_word_or_property(query, pos, profile)
            tokens.append(token)
        else:
            raise ProfileQueryError(f"Unexpected character: {char}", pos)
    tokens.append(_ProfileToken("eof", "", pos))
    return tuple(tokens)


def _parse_quoted_string(
    query: str,
    pos: int,
    *,
    case_sensitive: bool,
) -> tuple[_ProfileToken, int]:
    start_pos = pos
    pos += 1
    value_chars: list[str] = []
    while pos < len(query):
        char = query[pos]
        if char == '"':
            return (
                _ProfileToken(
                    "string",
                    "".join(value_chars),
                    start_pos,
                    case_sensitive=case_sensitive,
                ),
                pos + 1,
            )
        if char == "\\":
            if pos + 1 >= len(query):
                raise ProfileQueryError("Unterminated escape sequence", pos)
            escaped = query[pos + 1]
            if escaped == "\\":
                value_chars.append("\\")
            elif escaped == '"':
                value_chars.append('"')
            elif escaped == "n":
                value_chars.append("\n")
            elif escaped == "r":
                value_chars.append("\r")
            elif escaped == "t":
                value_chars.append("\t")
            else:
                raise ProfileQueryError(f"Invalid escape sequence: \\{escaped}", pos)
            pos += 2
            continue
        value_chars.append(char)
        pos += 1
    raise ProfileQueryError("Unterminated string", start_pos)


def _parse_bang(
    query: str,
    pos: int,
    profile: CompiledQueryProfile,
) -> tuple[_ProfileToken, int]:
    if query[pos : pos + 3] == "!!!":
        return (_predicate_token("error_suffix", "!!!", pos, profile), pos + 3)
    if query[pos : pos + 2] == "!!" and _standalone_at(query, pos + 2):
        return (_not_predicate_token("error_suffix", "!!", pos, profile), pos + 2)
    if query[pos : pos + 2] == "!@" and _standalone_at(query, pos + 2):
        return (_not_predicate_token("running_agent", "!@", pos, profile), pos + 2)
    if query[pos : pos + 2] == "!$" and _standalone_at(query, pos + 2):
        return (_not_predicate_token("running_process", "!$", pos, profile), pos + 2)
    if _standalone_at(query, pos + 1):
        return (_predicate_token("error_suffix", "!", pos, profile), pos + 1)
    return (_ProfileToken("not", "!", pos), pos + 1)


def _parse_predicate_sigil(
    query: str,
    pos: int,
    profile: CompiledQueryProfile,
) -> tuple[_ProfileToken, int]:
    char = query[pos]
    predicate = "running_agent" if char == "@" else "running_process"
    triple = "@@@" if char == "@" else "$$$"
    if query[pos : pos + 3] == triple:
        return (_predicate_token(predicate, triple, pos, profile), pos + 3)
    if _standalone_at(query, pos + 1):
        return (_predicate_token(predicate, char, pos, profile), pos + 1)
    raise ProfileQueryError(f"Unexpected character: {char}", pos)


def _parse_macro(
    query: str,
    pos: int,
    profile: CompiledQueryProfile,
) -> tuple[_ProfileToken, int]:
    trigger = query[pos]
    if pos + 1 >= len(query):
        raise ProfileQueryError(f"Invalid {trigger} shorthand", pos)
    letter = query[pos + 1].lower()
    macro = next(
        (
            item
            for item in profile.macros
            if item.trigger == trigger and item.letter.lower() == letter
        ),
        None,
    )
    if macro is None:
        valid = ", ".join(f"{item.trigger}{item.letter}" for item in profile.macros)
        raise ProfileQueryError(f"Invalid {trigger} shorthand (use {valid})", pos)
    field = require_filterable_field(profile, macro.field, pos)
    value = normalize_query_value(field, macro.value, position=pos)
    return (_ProfileToken("property", value, pos, property_key=macro.field), pos + 2)


def _parse_field_sigil(
    query: str,
    pos: int,
    profile: CompiledQueryProfile,
) -> tuple[_ProfileToken, int]:
    sigil = query[pos]
    spec = next(item for item in profile.sigils if item.sigil == sigil)
    field = require_filterable_field(profile, spec.field, pos)
    value, next_pos = _parse_property_value(query, pos + 1)
    normalized = normalize_query_value(field, value, position=pos)
    return (
        _ProfileToken("property", normalized, pos, property_key=spec.field),
        next_pos,
    )


def _parse_word_or_property(
    query: str,
    pos: int,
    profile: CompiledQueryProfile,
) -> tuple[_ProfileToken, int]:
    start = pos
    while pos < len(query) and _is_bare_word_char(query[pos]):
        pos += 1
    word = query[start:pos]
    word_upper = word.upper()
    if word_upper == "AND":
        return (_ProfileToken("and", word, start), pos)
    if word_upper == "OR":
        return (_ProfileToken("or", word, start), pos)
    if word_upper == "NOT":
        return (_ProfileToken("not", word, start), pos)
    if pos < len(query) and query[pos] == ":":
        key = word.casefold()
        field = require_filterable_field(profile, key, start)
        value, pos = _parse_property_value(
            query,
            pos + 1,
            extended=key == "artifact",
        )
        normalized = normalize_query_value(field, value, position=start)
        return (_ProfileToken("property", normalized, start, property_key=key), pos)
    return (_ProfileToken("string", word, start), pos)


def _parse_property_value(
    query: str,
    pos: int,
    *,
    extended: bool = False,
) -> tuple[str, int]:
    if pos >= len(query):
        raise ProfileQueryError("Expected property value", pos)
    if query[pos] == '"':
        token, next_pos = _parse_quoted_string(query, pos, case_sensitive=False)
        return token.value, next_pos
    if extended:
        start = pos
        while pos < len(query) and not query[pos].isspace() and query[pos] not in "()":
            pos += 1
        if pos == start:
            raise ProfileQueryError("Expected property value", pos)
        return query[start:pos], pos
    match = _PROPERTY_VALUE_RE.match(query, pos)
    if match is None:
        raise ProfileQueryError("Expected property value", pos)
    return match.group(0), match.end()


def _predicate_token(
    predicate: str,
    value: str,
    position: int,
    profile: CompiledQueryProfile,
) -> _ProfileToken:
    if predicate not in profile.predicates:
        raise ProfileQueryError(f"Predicate {predicate!r} is not enabled", position)
    return _ProfileToken("predicate", value, position, predicate=predicate)


def _not_predicate_token(
    predicate: str,
    value: str,
    position: int,
    profile: CompiledQueryProfile,
) -> _ProfileToken:
    if predicate not in profile.predicates:
        raise ProfileQueryError(f"Predicate {predicate!r} is not enabled", position)
    return _ProfileToken("not_predicate", value, position, predicate=predicate)


def _predicate_expr(token: _ProfileToken) -> StringMatch:
    assert token.predicate is not None
    return _predicate_expr_for_name(token.predicate)


def _predicate_expr_for_name(name: str) -> StringMatch:
    if name == "error_suffix":
        return StringMatch(ERROR_SUFFIX_QUERY, is_error_suffix=True)
    if name == "running_agent":
        return StringMatch(RUNNING_AGENT_QUERY, is_running_agent=True)
    if name == "running_process":
        return StringMatch(RUNNING_PROCESS_QUERY, is_running_process=True)
    raise ProfileQueryError(f"Unknown predicate {name!r}", 0)


def _standalone_at(query: str, pos: int) -> bool:
    return pos >= len(query) or query[pos].isspace()


def _is_bare_word_start_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_bare_word_char(char: str) -> bool:
    return char.isalnum() or char in "_.-"


__all__ = ["parse_boolean_query"]

"""Profile-driven Python reference parser and evaluator for Artifact rows."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import re
from typing import Literal

from sase.ace.query.parser import QueryParseError
from sase.ace.query.profile_evaluator import (
    ArtifactQueryEvaluationContext,
    ArtifactQueryRow,
    ArtifactQueryRowInput,
    ProfileFieldValue,
    build_query_context_for_profile,
    coerce_artifact_query_row,
    evaluate_query_for_profile,
    evaluate_query_with_profile_context,
)
from sase.ace.query.types import (
    ERROR_SUFFIX_QUERY,
    RUNNING_AGENT_QUERY,
    RUNNING_PROCESS_QUERY,
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.ace.query_profile import CompiledQueryProfile, QueryFieldSpec
from sase.filter_tokens import (
    FilterQueryError,
    FilterToken,
    quote_value,
    split_unquoted,
    tokenize as tokenize_flat_filter,
    unquoted_index,
)
from sase.vcs_log.dates import (
    TimeBoundary,
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)

_PROPERTY_VALUE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_BOOLEAN_VALUES = {"true": True, "false": False}


class ProfileQueryError(QueryParseError):
    """Profile-aware query parse failure with the standard query error shape."""


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


def parse_query_for_profile(query: str, profile: CompiledQueryProfile) -> QueryExpr:
    """Parse *query* using the syntax declared by *profile*."""

    if profile.boolean:
        return _BooleanProfileParser(query, profile).parse()
    return _parse_flat_query_for_profile(query, profile)


def _parse_flat_query_for_profile(
    query: str,
    profile: CompiledQueryProfile,
) -> QueryExpr:
    """Parse a flat-token pane query into the shared query AST."""

    tokens = _flat_tokens(query)
    if not tokens:
        raise ProfileQueryError("Empty query", 0)

    field_terms: dict[str, list[PropertyMatch]] = {}
    excluded_field_terms: dict[str, list[PropertyMatch]] = {}
    text_terms: list[StringMatch] = []
    excluded_text_terms: list[StringMatch] = []
    single_fields: dict[str, FilterToken] = {}

    for token in tokens:
        colon = unquoted_index(token, ":")
        if token.wholly_quoted or colon < 0:
            _append_text_term(
                token,
                text_terms=text_terms,
                excluded_text_terms=excluded_text_terms,
                profile=profile,
            )
            continue

        key_start = 1 if token.negated else 0
        key = token.value[key_start:colon].casefold()
        field_spec = _require_filterable_field(profile, key, token.start)
        if token.negated and not field_spec.negatable:
            raise ProfileQueryError(f"{key}: may not be negated", token.start)

        value = token.value[colon + 1 :]
        value_quoted = token.quoted[colon + 1 :]
        if not value:
            raise ProfileQueryError(f"{key}: requires a value", token.start)

        parts = split_unquoted(value, value_quoted, ",")
        if len(parts) > 1 and not field_spec.repeatable:
            raise ProfileQueryError(
                f"{key}: does not accept comma-separated values",
                token.start,
            )
        if any(not part for part in parts):
            raise ProfileQueryError(f"{key}: contains an empty value", token.start)
        if not field_spec.repeatable:
            prior = single_fields.get(key)
            if prior is not None:
                raise ProfileQueryError(f"{key}: may only appear once", token.start)
            single_fields[key] = token

        normalized = tuple(
            _normalize_query_value(field_spec, part, position=token.start)
            for part in parts
        )
        terms = [PropertyMatch(key=key, value=value) for value in normalized]
        target = excluded_field_terms if token.negated else field_terms
        target.setdefault(key, []).extend(terms)

    expressions: list[QueryExpr] = []
    for key in _profile_field_order(profile):
        positive = field_terms.get(key, ())
        if positive:
            expressions.append(_or_terms(positive))
        negative = excluded_field_terms.get(key, ())
        if negative:
            expressions.append(NotExpr(_or_terms(negative)))
    expressions.extend(text_terms)
    expressions.extend(NotExpr(term) for term in excluded_text_terms)
    return _and_terms(expressions)


def evaluate_query_many_for_profile(
    query: str,
    entries: Iterable[ArtifactQueryRowInput],
    profile: CompiledQueryProfile,
) -> list[bool]:
    """Parse and evaluate *query* against every entry under *profile*."""

    expr = parse_query_for_profile(query, profile)
    ctx = build_query_context_for_profile(profile, entries)
    return [evaluate_query_for_profile(expr, row, profile) for row in ctx.rows]


def canonical_query_for_profile(query: str, profile: CompiledQueryProfile) -> str:
    """Return the flat-token canonical query for *profile*.

    Boolean profiles use the existing AST canonicalizer; flat profiles retain
    their stable token order and quote only where the shared filter-token lexer
    requires it.
    """

    from sase.ace.query.types import to_canonical_string

    if profile.boolean:
        return to_canonical_string(parse_query_for_profile(query, profile))
    return _canonical_flat_query(query, profile)


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
        return _or_terms(operands)

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
        return _and_terms(operands)

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
        elif char.isalpha() or char == "_":
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
    field = _require_filterable_field(profile, macro.field, pos)
    value = _normalize_query_value(field, macro.value, position=pos)
    return (_ProfileToken("property", value, pos, property_key=macro.field), pos + 2)


def _parse_field_sigil(
    query: str,
    pos: int,
    profile: CompiledQueryProfile,
) -> tuple[_ProfileToken, int]:
    sigil = query[pos]
    spec = next(item for item in profile.sigils if item.sigil == sigil)
    field = _require_filterable_field(profile, spec.field, pos)
    value, next_pos = _parse_property_value(query, pos + 1)
    normalized = _normalize_query_value(field, value, position=pos)
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
    while pos < len(query) and (query[pos].isalnum() or query[pos] in "_-"):
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
        field = _require_filterable_field(profile, key, start)
        value, pos = _parse_property_value(query, pos + 1)
        normalized = _normalize_query_value(field, value, position=start)
        return (_ProfileToken("property", normalized, start, property_key=key), pos)
    return (_ProfileToken("string", word, start), pos)


def _parse_property_value(query: str, pos: int) -> tuple[str, int]:
    if pos >= len(query):
        raise ProfileQueryError("Expected property value", pos)
    if query[pos] == '"':
        token, next_pos = _parse_quoted_string(query, pos, case_sensitive=False)
        return token.value, next_pos
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


def _flat_tokens(query: str) -> tuple[FilterToken, ...]:
    try:
        return tokenize_flat_filter(query)
    except FilterQueryError as exc:
        raise ProfileQueryError(exc.message, exc.start) from exc


def _append_text_term(
    token: FilterToken,
    *,
    text_terms: list[StringMatch],
    excluded_text_terms: list[StringMatch],
    profile: CompiledQueryProfile,
) -> None:
    if token.negated and not profile.negatable_fields():
        raise ProfileQueryError(
            "filters for this pane do not support negation", token.start
        )
    value = token.body
    if not value:
        raise ProfileQueryError("Free-text terms must not be empty", token.start)
    target = excluded_text_terms if token.negated else text_terms
    target.append(StringMatch(value))


def _require_filterable_field(
    profile: CompiledQueryProfile,
    key: str,
    position: int,
) -> QueryFieldSpec:
    field = profile.field(key)
    if field is None or not field.filterable:
        valid = ", ".join(item.key for item in profile.fields if item.filterable)
        raise ProfileQueryError(
            f"Unknown filter key {key!r}"
            + (f" (valid keys: {valid})" if valid else ""),
            position,
        )
    return field


def _normalize_query_value(
    field: QueryFieldSpec,
    value: str,
    *,
    position: int,
) -> str:
    if field.value_kind == "enum":
        allowed = {item.casefold(): item for item in field.static_values}
        normalized = allowed.get(value.casefold())
        if normalized is None:
            raise ProfileQueryError(
                f"{field.key}: value {value!r} must be one of "
                f"{', '.join(field.static_values)}",
                position,
            )
        return normalized
    if field.value_kind == "bool":
        normalized_bool = _BOOLEAN_VALUES.get(value.casefold())
        if normalized_bool is None:
            raise ProfileQueryError(f"{field.key}: must be 'true' or 'false'", position)
        return "true" if normalized_bool else "false"
    if field.value_kind == "int":
        if not _INTEGER_RE.fullmatch(value):
            raise ProfileQueryError(f"{field.key}: must be an integer", position)
        return str(int(value))
    if field.value_kind == "date":
        return str(_parse_date_bound_value(field.key, value, position=position))
    return value


def _parse_date_bound_value(key: str, value: str, *, position: int) -> int:
    boundary: TimeBoundary = "until" if key == "until" else "since"
    try:
        return parse_time_bound(value).resolve(
            now=normalize_reference_time(),
            boundary=boundary,
        )
    except VcsLogDateError as exc:
        raise ProfileQueryError(str(exc), position) from exc


def _profile_field_order(profile: CompiledQueryProfile) -> tuple[str, ...]:
    return tuple(item.key for item in profile.fields if item.filterable)


def _or_terms(terms: Sequence[QueryExpr]) -> QueryExpr:
    if len(terms) == 1:
        return terms[0]
    return OrExpr(list(terms))


def _and_terms(terms: Sequence[QueryExpr]) -> QueryExpr:
    if not terms:
        raise ProfileQueryError("Empty query", 0)
    if len(terms) == 1:
        return terms[0]
    return AndExpr(list(terms))


def _canonical_flat_query(query: str, profile: CompiledQueryProfile) -> str:
    expr = _parse_flat_query_for_profile(query, profile)
    if isinstance(expr, AndExpr):
        terms = expr.operands
    else:
        terms = [expr]
    tokens: list[str] = []
    for term in terms:
        if isinstance(term, PropertyMatch):
            tokens.append(f"{term.key}:{quote_value(term.value, keyed=True)}")
        elif isinstance(term, NotExpr) and isinstance(term.operand, PropertyMatch):
            inner = term.operand
            tokens.append(f"-{inner.key}:{quote_value(inner.value, keyed=True)}")
        elif isinstance(term, StringMatch):
            tokens.append(quote_value(term.value, keyed=False))
        elif isinstance(term, NotExpr) and isinstance(term.operand, StringMatch):
            tokens.append(f"-{quote_value(term.operand.value, keyed=False)}")
        else:
            # Comma-list OR groups have no single legacy spelling after AST
            # grouping, so fall back to boolean canonical text for visibility.
            from sase.ace.query.types import to_canonical_string

            tokens.append(to_canonical_string(term))
    return " ".join(tokens)


__all__ = [
    "ArtifactQueryEvaluationContext",
    "ArtifactQueryRow",
    "ArtifactQueryRowInput",
    "ProfileFieldValue",
    "ProfileQueryError",
    "build_query_context_for_profile",
    "canonical_query_for_profile",
    "coerce_artifact_query_row",
    "evaluate_query_for_profile",
    "evaluate_query_many_for_profile",
    "evaluate_query_with_profile_context",
    "parse_query_for_profile",
]

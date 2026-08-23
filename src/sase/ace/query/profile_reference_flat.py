"""Flat-token parser and canonicalizer for profile-driven queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.ace.query.profile_reference_support import (
    ProfileQueryError,
    and_terms,
    normalize_query_value,
    or_terms,
    require_filterable_field,
)
from sase.ace.query.types import (
    NotExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.ace.query_profile import CompiledQueryProfile, QueryFieldSpec
from sase.ace.query_profile.registry import HOST_PREDICATES
from sase.filter_tokens import (
    FilterQueryError,
    FilterToken,
    quote_value,
    split_unquoted,
    tokenize as tokenize_flat_filter,
    unquoted_index,
)

_PredicateSpelling = Literal["!!!", "!!", "@@@", "!@", "$$$", "!$", "*"]


@dataclass(frozen=True, slots=True)
class _FlatTextClause:
    value: str
    negated: bool


@dataclass(frozen=True, slots=True)
class _FlatFieldClause:
    key: str
    values: tuple[str, ...]
    negated: bool


@dataclass(frozen=True, slots=True)
class _FlatPredicateClause:
    expr: QueryExpr
    spelling: _PredicateSpelling


_FlatClause = _FlatTextClause | _FlatFieldClause | _FlatPredicateClause


def parse_flat_query(query: str, profile: CompiledQueryProfile) -> QueryExpr:
    """Parse a flat-token pane query into the shared query AST."""

    clauses = _flat_clauses(query, profile)
    field_terms: dict[str, list[PropertyMatch]] = {}
    excluded_field_terms: dict[str, list[PropertyMatch]] = {}
    text_terms: list[StringMatch] = []
    excluded_text_terms: list[StringMatch] = []

    expressions: list[QueryExpr] = []
    for clause in clauses:
        if isinstance(clause, _FlatFieldClause):
            terms = [
                PropertyMatch(key=clause.key, value=value) for value in clause.values
            ]
            field_target = excluded_field_terms if clause.negated else field_terms
            field_target.setdefault(clause.key, []).extend(terms)
        elif isinstance(clause, _FlatTextClause):
            text_target = excluded_text_terms if clause.negated else text_terms
            text_target.append(StringMatch(clause.value))
        else:
            expressions.append(clause.expr)

    for key in _profile_field_order(profile):
        positive = field_terms.get(key, ())
        if positive:
            expressions.append(or_terms(positive))
        negative = excluded_field_terms.get(key, ())
        if negative:
            expressions.append(NotExpr(or_terms(negative)))
    expressions.extend(text_terms)
    expressions.extend(NotExpr(term) for term in excluded_text_terms)
    return and_terms(expressions)


def canonical_flat_query(query: str, profile: CompiledQueryProfile) -> str:
    """Return the stable flat-token canonical form of a profile query."""

    clauses = _flat_clauses(query, profile)
    positive_fields: dict[str, list[str]] = {}
    negative_fields: dict[str, list[str]] = {}
    predicates: list[str] = []
    text_tokens: list[str] = []
    for clause in clauses:
        if isinstance(clause, _FlatFieldClause):
            target = negative_fields if clause.negated else positive_fields
            target.setdefault(clause.key, []).extend(clause.values)
        elif isinstance(clause, _FlatPredicateClause):
            predicates.append(clause.spelling)
        else:
            rendered = _render_text_value(clause.value, profile)
            text_tokens.append(f"-{rendered}" if clause.negated else rendered)

    tokens: list[str] = []
    for key in _profile_field_order(profile):
        if values := positive_fields.get(key):
            tokens.append(f"{key}:{_render_field_values(values)}")
        if values := negative_fields.get(key):
            tokens.append(f"-{key}:{_render_field_values(values)}")
    tokens.extend(predicates)
    tokens.extend(text_tokens)
    return " ".join(tokens)


def _flat_clauses(
    query: str,
    profile: CompiledQueryProfile,
) -> tuple[_FlatClause, ...]:
    tokens = _flat_tokens(query)
    if not tokens:
        raise ProfileQueryError("Empty query", 0)

    clauses: list[_FlatClause] = []
    single_fields: dict[str, FilterToken] = {}
    for token in tokens:
        if predicate := _predicate_clause(token, profile):
            clauses.append(predicate)
            continue
        colon = unquoted_index(token, ":")
        if bare_flag := _bare_bool_clause(token, profile, colon=colon):
            field_spec = require_filterable_field(profile, bare_flag.key, token.start)
            if token.negated and not field_spec.negatable:
                raise ProfileQueryError(
                    f"{bare_flag.key}: may not be negated", token.start
                )
            _record_single_field(single_fields, bare_flag.key, token, field_spec)
            clauses.append(bare_flag)
            continue
        if token.wholly_quoted or colon < 0:
            clauses.append(_text_clause(token, profile=profile))
            continue

        key_start = 1 if token.negated else 0
        key = token.value[key_start:colon].casefold()
        field_spec = require_filterable_field(profile, key, token.start)
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
        _record_single_field(single_fields, key, token, field_spec)

        clauses.append(
            _FlatFieldClause(
                key=key,
                values=tuple(
                    normalize_query_value(field_spec, part, position=token.start)
                    for part in parts
                ),
                negated=token.negated,
            )
        )
    return tuple(clauses)


def _bare_bool_clause(
    token: FilterToken,
    profile: CompiledQueryProfile,
    *,
    colon: int,
) -> _FlatFieldClause | None:
    if token.wholly_quoted or colon >= 0 or any(token.body_quoted):
        return None
    key = token.body.casefold()
    field_spec = profile.field(key)
    if (
        field_spec is None
        or not field_spec.filterable
        or field_spec.value_kind != "bool"
    ):
        return None
    return _FlatFieldClause(key=key, values=("true",), negated=token.negated)


def _record_single_field(
    single_fields: dict[str, FilterToken],
    key: str,
    token: FilterToken,
    field_spec: QueryFieldSpec,
) -> None:
    if field_spec.repeatable:
        return
    prior = single_fields.get(key)
    if prior is not None:
        raise ProfileQueryError(f"{key}: may only appear once", token.start)
    single_fields[key] = token


def _flat_tokens(query: str) -> tuple[FilterToken, ...]:
    try:
        return tokenize_flat_filter(query)
    except FilterQueryError as exc:
        raise ProfileQueryError(exc.message, exc.start) from exc


def _text_clause(
    token: FilterToken,
    *,
    profile: CompiledQueryProfile,
) -> _FlatTextClause:
    if token.negated and not profile.negatable_fields():
        raise ProfileQueryError(
            "filters for this pane do not support negation", token.start
        )
    value = token.body
    if not value:
        raise ProfileQueryError("Free-text terms must not be empty", token.start)
    return _FlatTextClause(
        value=value,
        negated=token.negated,
    )


def _predicate_clause(
    token: FilterToken,
    profile: CompiledQueryProfile,
) -> _FlatPredicateClause | None:
    if token.negated or token.wholly_quoted:
        return None
    body = token.body
    if body in {"!", "!!!"} and _has_predicate(profile, "error_suffix"):
        return _FlatPredicateClause(_predicate_expr("error_suffix"), "!!!")
    if body == "!!" and _has_predicate(profile, "error_suffix"):
        return _FlatPredicateClause(NotExpr(_predicate_expr("error_suffix")), "!!")
    if body in {"@", "@@@"} and _has_predicate(profile, "running_agent"):
        return _FlatPredicateClause(_predicate_expr("running_agent"), "@@@")
    if body == "!@" and _has_predicate(profile, "running_agent"):
        return _FlatPredicateClause(NotExpr(_predicate_expr("running_agent")), "!@")
    if body in {"$", "$$$"} and _has_predicate(profile, "running_process"):
        return _FlatPredicateClause(_predicate_expr("running_process"), "$$$")
    if body == "!$" and _has_predicate(profile, "running_process"):
        return _FlatPredicateClause(NotExpr(_predicate_expr("running_process")), "!$")
    if body == "*" and profile.any_special:
        return _FlatPredicateClause(
            or_terms(tuple(_predicate_expr(name) for name in profile.predicates)),
            "*",
        )
    return None


def _has_predicate(profile: CompiledQueryProfile, name: str) -> bool:
    return name in profile.predicates and name in HOST_PREDICATES


def _predicate_expr(name: str) -> StringMatch:
    if name == "running_agent":
        return StringMatch("@@@ internal marker", is_running_agent=True)
    if name == "running_process":
        return StringMatch("$$$ internal marker", is_running_process=True)
    return StringMatch(" - (!: ", is_error_suffix=True)


def _profile_field_order(profile: CompiledQueryProfile) -> tuple[str, ...]:
    return tuple(item.key for item in profile.fields if item.filterable)


def _render_field_values(values: list[str]) -> str:
    return ",".join(quote_value(value, keyed=True) for value in values)


def _render_text_value(value: str, profile: CompiledQueryProfile) -> str:
    rendered = quote_value(value, keyed=False)
    if rendered == value and _is_filterable_bool_key(value, profile):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return rendered


def _is_filterable_bool_key(value: str, profile: CompiledQueryProfile) -> bool:
    field_spec = profile.field(value.casefold())
    return (
        field_spec is not None
        and field_spec.filterable
        and field_spec.value_kind == "bool"
    )


__all__ = ["canonical_flat_query", "parse_flat_query"]

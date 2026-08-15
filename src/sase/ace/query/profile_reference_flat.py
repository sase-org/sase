"""Flat-token parser and canonicalizer for profile-driven queries."""

from __future__ import annotations

from typing import cast

from sase.ace.query.profile_reference_support import (
    ProfileQueryError,
    and_terms,
    normalize_query_value,
    or_terms,
    require_filterable_field,
)
from sase.ace.query.types import (
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
    to_canonical_string,
)
from sase.ace.query_profile import CompiledQueryProfile
from sase.filter_tokens import (
    FilterQueryError,
    FilterToken,
    quote_value,
    split_unquoted,
    tokenize as tokenize_flat_filter,
    unquoted_index,
)


def parse_flat_query(query: str, profile: CompiledQueryProfile) -> QueryExpr:
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
        if not field_spec.repeatable:
            prior = single_fields.get(key)
            if prior is not None:
                raise ProfileQueryError(f"{key}: may only appear once", token.start)
            single_fields[key] = token

        normalized = tuple(
            normalize_query_value(field_spec, part, position=token.start)
            for part in parts
        )
        terms = [PropertyMatch(key=key, value=value) for value in normalized]
        target = excluded_field_terms if token.negated else field_terms
        target.setdefault(key, []).extend(terms)

    expressions: list[QueryExpr] = []
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

    expr = parse_flat_query(query, profile)
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
        elif isinstance(term, OrExpr) and (key := _same_key_property_group(term)):
            values = ",".join(
                quote_value(cast(PropertyMatch, op).value, keyed=True)
                for op in term.operands
            )
            tokens.append(f"{key}:{values}")
        else:
            # Flat parsing only groups same-key PropertyMatch terms into an
            # OrExpr. Keep a defensive fallback in case that invariant changes.
            tokens.append(to_canonical_string(term))
    return " ".join(tokens)


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


def _profile_field_order(profile: CompiledQueryProfile) -> tuple[str, ...]:
    return tuple(item.key for item in profile.fields if item.filterable)


def _same_key_property_group(term: OrExpr) -> str | None:
    """Return the shared key for an all-property, single-key OR group."""

    if not term.operands or not all(
        isinstance(op, PropertyMatch) for op in term.operands
    ):
        return None
    keys = {cast(PropertyMatch, op).key for op in term.operands}
    return keys.pop() if len(keys) == 1 else None


__all__ = ["canonical_flat_query", "parse_flat_query"]

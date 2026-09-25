"""Compatibility normalizers for retired agent-family user syntax.

Keep every temporary alias for the agent-session terminology migration in this
module. Durable readers may request the unconditional legacy path; authored
input follows the ``legacy_agent_family_syntax`` sunset flag.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from sase.agent._agent_session_attach_types import (
    AGENT_SESSION_ATTACH_ENV,
    LEGACY_AGENT_FAMILY_ATTACH_ENV,
)
from sase.feature_flags import FeatureFlag, current_flags

if TYPE_CHECKING:
    from sase.ace.query.types import QueryExpr
    from sase.ace.query_profile import CompiledQueryProfile

_LEGACY_DIRECTIVE_KEY = "family"
_SESSION_DIRECTIVE_KEY = "session"
_LEGACY_FORK = "family"
_SESSION_FORK = "session"
_LEGACY_QUERY_FIELD = "family"
_SESSION_QUERY_FIELD = "session"
_LEGACY_QUERY_KIND = "family"
_SESSION_QUERY_KIND = "session"


def _legacy_agent_family_syntax_enabled() -> bool:
    """Return whether retired user-authored agent-family syntax is accepted."""
    return current_flags().enabled(FeatureFlag.legacy_agent_family_syntax)


def _retired_agent_family_syntax_message(legacy: str, replacement: str) -> str:
    """Return the consistent replacement hint for one retired spelling."""
    return f"{legacy} is retired; use {replacement}"


def normalize_agent_session_directive_args(
    named_args: Mapping[str, str],
) -> dict[str, str]:
    """Normalize the old ``family=`` %id keyword to ``session=`` when allowed."""
    normalized = dict(named_args)
    has_legacy = _LEGACY_DIRECTIVE_KEY in normalized
    has_canonical = _SESSION_DIRECTIVE_KEY in normalized
    if has_legacy and has_canonical:
        raise ValueError("family= and session= cannot be combined; use only session=.")
    if not has_legacy:
        return normalized
    if not _legacy_agent_family_syntax_enabled():
        raise ValueError(_retired_agent_family_syntax_message("family=", "session="))
    normalized[_SESSION_DIRECTIVE_KEY] = normalized.pop(_LEGACY_DIRECTIVE_KEY)
    return normalized


def normalize_agent_session_fork(
    value: object,
    *,
    persisted: bool = False,
) -> object:
    """Normalize a gate fork value, preserving old durable records unconditionally."""
    if value != _LEGACY_FORK:
        return value
    if persisted or _legacy_agent_family_syntax_enabled():
        return _SESSION_FORK
    raise ValueError(
        _retired_agent_family_syntax_message('"fork": "family"', '"fork": "session"')
    )


def normalize_persisted_agent_session_fork(value: object) -> object:
    """Normalize a pre-rename durable gate fork regardless of the sunset flag."""
    return normalize_agent_session_fork(value, persisted=True)


def agent_session_attach_env_value(env: Mapping[str, str]) -> str | None:
    """Read the canonical attach payload, or a permitted legacy fallback."""
    canonical = env.get(AGENT_SESSION_ATTACH_ENV)
    if canonical:
        return canonical
    legacy = env.get(LEGACY_AGENT_FAMILY_ATTACH_ENV)
    if legacy and _legacy_agent_family_syntax_enabled():
        return legacy
    return None


def normalize_agent_session_query_expr(expr: QueryExpr) -> QueryExpr:
    """Rewrite retired agent-family terms in a parsed agent query AST.

    ``family:<value>`` becomes ``session:<value>`` and ``kind:family``
    becomes ``kind:session`` at every level of the boolean AST. All other
    terms — including free-text mentions of "family" and ``family`` as the
    value of any other field — pass through unchanged.
    """
    from sase.ace.query.types import AndExpr, NotExpr, OrExpr, PropertyMatch

    if isinstance(expr, PropertyMatch):
        if expr.key == _LEGACY_QUERY_FIELD:
            return PropertyMatch(key=_SESSION_QUERY_FIELD, value=expr.value)
        if expr.key == "kind" and expr.value.casefold() == _LEGACY_QUERY_KIND:
            return PropertyMatch(key=expr.key, value=_SESSION_QUERY_KIND)
        return expr
    if isinstance(expr, NotExpr):
        rewritten = normalize_agent_session_query_expr(expr.operand)
        return expr if rewritten is expr.operand else NotExpr(operand=rewritten)
    if isinstance(expr, (AndExpr, OrExpr)):
        rewritten_operands = [
            normalize_agent_session_query_expr(operand) for operand in expr.operands
        ]
        if all(
            rewritten is original
            for rewritten, original in zip(
                rewritten_operands, expr.operands, strict=True
            )
        ):
            return expr
        return type(expr)(operands=rewritten_operands)
    return expr


def normalize_agent_session_query_text(
    raw: str,
    profile: CompiledQueryProfile,
) -> str:
    """Return *raw* with retired agent-family query terms in canonical form.

    The rewrite works on the parsed query AST, never on the raw text: the
    query is parsed (tolerating the retired ``family`` field and the retired
    ``kind:family`` value), :func:`normalize_agent_session_query_expr`
    rewrites the AST, and the canonical session spelling is returned.

    With the ``legacy_agent_family_syntax`` flag on, a query using the
    retired spellings returns its canonical text. With the flag off, a query
    using them raises :class:`ProfileQueryError` naming the
    ``session:``/``kind:session`` replacements. Queries that fail to parse
    for any other reason raise the original parse error either way.
    """
    from sase.ace.query.limit_token import LimitTokenError, extract_limit
    from sase.ace.query.profile_reference import parse_query_for_profile
    from sase.ace.query.profile_reference_support import ProfileQueryError

    try:
        remainder, _cap = extract_limit(raw)
    except LimitTokenError:
        # Leave host-owned limit errors to the caller's own limit handling.
        return raw
    if not remainder.strip():
        # Empty and limit-only queries carry no field terms; downstream
        # scoping handles them unchanged.
        return raw
    try:
        parse_query_for_profile(raw, profile)
    except ProfileQueryError as original_error:
        return _normalize_agent_session_query_after_error(raw, profile, original_error)
    return raw


def _normalize_agent_session_query_after_error(
    raw: str,
    profile: CompiledQueryProfile,
    original_error: Exception,
) -> str:
    """Retry a failed agent-query parse tolerating retired family spellings."""
    from dataclasses import replace as _replace

    from sase.ace.query.profile_reference import parse_query_for_profile
    from sase.ace.query.profile_reference_support import ProfileQueryError
    from sase.ace.query.types import to_canonical_string
    from sase.ace.query_profile.types import QueryFieldSpec

    legacy_fields: list[QueryFieldSpec] = []
    for field in profile.fields:
        if field.key == "kind":
            legacy_fields.append(
                field
                if _LEGACY_QUERY_KIND in tuple(field.static_values)
                else _replace(
                    field,
                    static_values=(*tuple(field.static_values), _LEGACY_QUERY_KIND),
                )
            )
        else:
            legacy_fields.append(field)
    legacy_fields.append(
        QueryFieldSpec(
            key=_LEGACY_QUERY_FIELD,
            exact_match=True,
            hint="retired alias of session:",
        )
    )
    tolerant_profile = _replace(profile, fields=tuple(legacy_fields))
    try:
        legacy_expr = parse_query_for_profile(raw, tolerant_profile)
    except ProfileQueryError:
        raise original_error from None
    rewritten = normalize_agent_session_query_expr(legacy_expr)
    if to_canonical_string(rewritten) == to_canonical_string(legacy_expr):
        raise original_error from None
    if not _legacy_agent_family_syntax_enabled():
        raise ProfileQueryError(
            _retired_agent_family_syntax_message(
                "family:/kind:family", "session:/kind:session"
            ),
            0,
        ) from None
    canonical = to_canonical_string(rewritten)
    # Validate the rewritten query against the canonical profile so genuine
    # errors elsewhere in the query still surface with canonical positions.
    try:
        parse_query_for_profile(canonical, profile)
    except ProfileQueryError:
        raise original_error from None
    from sase.ace.query.limit_token import extract_limit, replace_limit

    stripped, cap = extract_limit(raw)
    if stripped == raw:
        return canonical
    if cap is None:
        # ``limit:all`` / ``limit:0`` spell unlimited; keep an explicit
        # token so callers still see a caller-supplied cap, not a default.
        return f"{canonical} limit:0" if canonical else "limit:0"
    return replace_limit(canonical, cap)


__all__ = [
    "agent_session_attach_env_value",
    "normalize_agent_session_directive_args",
    "normalize_agent_session_fork",
    "normalize_agent_session_query_expr",
    "normalize_agent_session_query_text",
    "normalize_persisted_agent_session_fork",
]

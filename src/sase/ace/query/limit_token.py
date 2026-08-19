"""Host-owned ``limit:`` token helpers shared by ACE list paging.

These helpers have no Textual imports. ``limit:`` is a presentation cap, not a
row-matching field: extract it before dialect parse / Rust eval, then slice.
"""

from __future__ import annotations

import re
from typing import Literal

from sase.filter_tokens import (
    FilterQueryError,
    FilterToken,
    error_for_token,
    tokenize,
    unquoted_index,
)

_NON_NEGATIVE_INTEGER_RE = re.compile(r"^\d+$")


class LimitTokenError(FilterQueryError):
    """A host-owned ``limit:`` token parse failure tied to an exact span."""


def extract_limit(query: str) -> tuple[str, int | None]:
    """Return ``(remainder, cap)`` after removing a host ``limit:`` token.

    ``None`` means unlimited: the token is absent, ``limit:all``, or
    ``limit:0``. Duplicate, negated, empty, and non-integer values raise
    :class:`LimitTokenError` the same way Stitches rejects them.
    """
    token, cap, remainder_parts = _scan_limit(query)
    if token is None:
        return query, None
    return " ".join(remainder_parts), cap


def ensure_limit(query: str, n: int) -> str:
    """Append ``limit:n`` when the query has no limit token.

    An explicit user token — including ``limit:all`` and ``limit:0`` — is
    left alone.
    """
    _require_positive_limit(n)
    token, _cap, _remainder = _scan_limit(query)
    if token is not None:
        return query
    return _append_token(query, f"limit:{n}")


def replace_limit(query: str, n: int) -> str:
    """Write a numeric ``limit:n``, preserving the rest of the query.

    Replaces an existing ``limit:`` token in place so surrounding tokens keep
    their original spelling and order. Appends when no limit token is present.
    """
    _require_positive_limit(n)
    token, _cap, _remainder = _scan_limit(query)
    replacement = f"limit:{n}"
    if token is None:
        return _append_token(query, replacement)
    return f"{query[: token.start]}{replacement}{query[token.end :]}"


def adjust_limit(
    current: int | None,
    page_size: int,
    direction: Literal["load_more", "unload"],
) -> int | None:
    """Apply plus-or-minus paging to a numeric cap.

    ``current`` is ``None`` when the list is unlimited. Load-more on an
    unlimited cap is a no-op. Unload of unlimited introduces ``page_size``.
    Unload never rises a user-typed cap below ``page_size`` up to that floor,
    and never drops to 0.
    """
    _require_positive_limit(page_size, name="page_size")
    if direction == "load_more":
        if current is None:
            return None
        return current + page_size
    if direction == "unload":
        if current is None:
            return page_size
        if current >= page_size:
            return max(page_size, current - page_size)
        return current
    raise ValueError(f"unknown limit direction: {direction!r}")


def _scan_limit(
    query: str,
) -> tuple[FilterToken | None, int | None, tuple[str, ...]]:
    remainder: list[str] = []
    found: FilterToken | None = None
    cap: int | None = None
    for token in tokenize(query, error_type=LimitTokenError):
        parsed = _parse_limit_token(token)
        if parsed is None:
            remainder.append(token.raw)
            continue
        if found is not None:
            raise _error("limit: may only appear once", token)
        found = token
        cap = parsed[0]
    return found, cap, tuple(remainder)


def _parse_limit_token(token: FilterToken) -> tuple[int | None] | None:
    """Return ``(cap,)`` for a limit token, or ``None`` when it is not one."""
    if token.wholly_quoted:
        return None
    colon = unquoted_index(token, ":")
    if colon < 0:
        return None
    key_start = 1 if token.negated else 0
    key = token.value[key_start:colon].casefold()
    if key != "limit":
        return None
    if token.negated:
        raise _error("limit: may not be negated", token)
    value = token.value[colon + 1 :]
    if not value:
        raise _error("limit: requires a value", token)
    if value.casefold() == "all":
        return (None,)
    if _NON_NEGATIVE_INTEGER_RE.fullmatch(value):
        parsed = int(value)
        return (None if parsed == 0 else parsed,)
    raise _error("limit: must be a non-negative integer or 'all'", token)


def _append_token(query: str, token: str) -> str:
    stripped = query.strip()
    if not stripped:
        return token
    return f"{stripped} {token}"


def _require_positive_limit(n: int, *, name: str = "n") -> None:
    if type(n) is not int or n < 1:
        raise ValueError(f"{name} must be an integer >= 1")


def _error(message: str, token: FilterToken) -> LimitTokenError:
    return error_for_token(  # type: ignore[return-value]
        message,
        token,
        error_type=LimitTokenError,
    )


__all__ = [
    "LimitTokenError",
    "adjust_limit",
    "ensure_limit",
    "extract_limit",
    "replace_limit",
]

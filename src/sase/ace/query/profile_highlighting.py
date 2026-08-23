"""Profile-driven query syntax highlighting for persistent filter bars.

Dispatches on :attr:`CompiledQueryProfile.boolean`: boolean-dialect panes
(Patches) reuse the existing hand-tuned :func:`tokenize_query_for_display`
unchanged. Flat-dialect panes (Stitches, Beads, Plans, Files, and every
``ref:<kind>`` provider) are classified with the same lexer the flat parser
uses -- :func:`sase.filter_tokens.tokenize` -- so the highlight can never
disagree with the parse; see
:func:`sase.ace.query.profile_reference_flat._flat_clauses` for the
reference classification this mirrors.
"""

from __future__ import annotations

from rich.text import Text

from sase.ace.query_profile import CompiledQueryProfile
from sase.filter_tokens import FilterQueryError, FilterToken, tokenize, unquoted_index

from .highlighting import QUERY_TOKEN_STYLES, tokenize_query_for_display

__all__ = ["highlight_query"]


def highlight_query(text: str, profile: CompiledQueryProfile) -> Text:
    """Render *text* as syntax-highlighted Rich ``Text`` for *profile*.

    Never raises: a half-typed or otherwise malformed query still renders,
    using whatever token spans the shared lexer can make sense of.
    """
    try:
        tokens = (
            tokenize_query_for_display(text)
            if profile.boolean
            else _classify_flat_query_tokens(text, profile)
        )
    except Exception:  # noqa: BLE001 - rendering must never raise
        return Text(text)

    rendered = Text(no_wrap=True)
    for token, token_type in tokens:
        style = QUERY_TOKEN_STYLES.get(token_type, "")
        if token_type == "keyword":
            rendered.append(token.upper(), style=style)
        elif style:
            rendered.append(token, style=style)
        else:
            rendered.append(token)
    return rendered


def _classify_flat_query_tokens(
    text: str,
    profile: CompiledQueryProfile,
) -> list[tuple[str, str]]:
    """Split *text* into ``(raw_span, style_key)`` pairs for the flat dialect.

    Branch order mirrors
    :func:`sase.ace.query.profile_reference_flat._flat_clauses` exactly
    (predicate, then sigil/macro shorthand, then ``key:value``, then free
    text) so the highlight can never disagree with what the flat parser
    would actually accept. Never raises.
    """
    try:
        tokens = tokenize(text, strict=False)
    except FilterQueryError:
        return [(text, "term")] if text else []

    known_keys = {key.casefold() for key in profile.filterable_fields()}
    known_keys.add("limit")
    sigil_map = {item.sigil: item.field for item in profile.sigils}
    macro_tokens = {f"{item.trigger}{item.letter}" for item in profile.macros}

    spans: list[tuple[str, str]] = []
    cursor = 0
    for token in tokens:
        if token.start > cursor:
            spans.append((text[cursor : token.start], "whitespace"))
        spans.extend(
            _classify_token(token, profile, known_keys, sigil_map, macro_tokens)
        )
        cursor = token.end
    if cursor < len(text):
        spans.append((text[cursor:], "whitespace"))
    return spans


def _classify_token(
    token: FilterToken,
    profile: CompiledQueryProfile,
    known_keys: set[str],
    sigil_map: dict[str, str],
    macro_tokens: set[str],
) -> list[tuple[str, str]]:
    raw = token.raw
    spans: list[tuple[str, str]] = []
    body_raw = raw
    if token.negated:
        spans.append((raw[:1], "negation"))
        body_raw = raw[1:]

    body = token.body

    if not token.negated and not token.wholly_quoted:
        predicate_style = _predicate_style(body, profile)
        if predicate_style is not None:
            spans.append((body_raw, predicate_style))
            return spans

        if body in macro_tokens:
            spans.append((body_raw, "shorthand"))
            return spans

        if body and body[0] in sigil_map and len(body) > 1:
            colon = unquoted_index(token, ":")
            if colon < 0:
                spans.append((body_raw, "shorthand"))
                return spans

    bare_flag_style = _bare_bool_flag_style(
        token,
        profile,
        colon=unquoted_index(token, ":"),
    )
    if bare_flag_style is not None:
        spans.append((body_raw, bare_flag_style))
        return spans

    if token.wholly_quoted or (
        token.negated and token.body_quoted and all(token.body_quoted)
    ):
        spans.append((body_raw, "quoted"))
        return spans

    colon = unquoted_index(token, ":")
    # `colon` indexes token.value, which still carries the leading '-' when
    # negated; `body_raw` already had that char stripped above, so shift by
    # one to keep the two aligned.
    key_end = colon - (1 if token.negated else 0) if colon >= 0 else -1
    if key_end >= 0 and '"' not in body_raw[:key_end]:
        key_raw = body_raw[:key_end]
        # The unquoted key segment never contains escapes, so decoded and
        # raw text agree here (both equal `key_raw`).
        style = "property_key" if key_raw.casefold() in known_keys else "unknown_key"
        spans.append((f"{key_raw}:", style))
        spans.extend(_split_raw_value(body_raw[key_end + 1 :]))
        return spans

    spans.append((body_raw, "term"))
    return spans


def _bare_bool_flag_style(
    token: FilterToken,
    profile: CompiledQueryProfile,
    *,
    colon: int,
) -> str | None:
    if token.wholly_quoted or colon >= 0 or any(token.body_quoted):
        return None
    field = profile.field(token.body.casefold())
    if field is None or not field.filterable or field.value_kind != "bool":
        return None
    return "property_key"


def _predicate_style(body: str, profile: CompiledQueryProfile) -> str | None:
    predicates = profile.predicates
    if body in {"!", "!!!", "!!"} and "error_suffix" in predicates:
        return "error_suffix"
    if body in {"@", "@@@", "!@"} and "running_agent" in predicates:
        return "running_agent"
    if body in {"$", "$$$", "!$"} and "running_process" in predicates:
        return "running_process"
    if body == "*" and profile.any_special:
        return "any_special"
    return None


def _split_raw_value(raw_value: str) -> list[tuple[str, str]]:
    """Split a raw ``key:`` value into quoted and unquoted style runs."""
    spans: list[tuple[str, str]] = []
    buf: list[str] = []
    style = "property_value"
    in_quotes = False
    index = 0
    length = len(raw_value)
    while index < length:
        char = raw_value[index]
        if char == '"':
            if not in_quotes:
                if buf:
                    spans.append(("".join(buf), style))
                buf = [char]
                in_quotes = True
                style = "quoted"
            else:
                buf.append(char)
                spans.append(("".join(buf), "quoted"))
                buf = []
                in_quotes = False
                style = "property_value"
            index += 1
            continue
        if in_quotes and char == "\\" and index + 1 < length:
            buf.append(char)
            buf.append(raw_value[index + 1])
            index += 2
            continue
        buf.append(char)
        index += 1
    if buf:
        spans.append(("".join(buf), style))
    return spans

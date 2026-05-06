"""Tokenizer for the agent query language.

Adapted from :mod:`sase.ace.query.tokenizer`. Differences:

* Closed property-key allowlist tailored to ``Agent`` fields.
* No ChangeSpec shorthand sigils (``%d``/``+proj``/``^anc``/``!!!``/``@@@`` etc.).
* New token types for ``age`` comparison operators (``<``, ``<=``, ``>``,
  ``>=``, ``=``) and ``(\\d+)(s|m|h|d)`` duration literals.
* Boolean-valued keys (``pinned``, ``hidden``, ``attention``) only accept
  ``true``/``false`` (case-insensitive); other values raise.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """Token types for the agent query language."""

    STRING = auto()  # Quoted, c-quoted, or bare-word string
    PROPERTY = auto()  # key:value (substring/enum/bool)
    DURATION = auto()  # age comparison: key + op + seconds
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    EOF = auto()


# Property keys that take a substring/enum/bool value via "key:value".
# Closed allowlist: any other "word:" prefix is a tokenizer error.
SUBSTRING_PROPERTY_KEYS = frozenset(
    {
        "status",
        "cl",
        "project",
        "name",
        "model",
        "provider",
        "tag",
        "text",
    }
)
ENUM_PROPERTY_KEYS: dict[str, frozenset[str]] = {
    "type": frozenset({"workflow", "run", "running"}),
    "source": frozenset({"axe", "manual"}),
    "needs": frozenset({"input"}),
}
BOOL_PROPERTY_KEYS = frozenset({"pinned", "hidden", "attention"})

# Keys that participate in age-style duration comparisons.
DURATION_PROPERTY_KEYS = frozenset({"age"})

VALID_PROPERTY_KEYS: frozenset[str] = (
    SUBSTRING_PROPERTY_KEYS
    | frozenset(ENUM_PROPERTY_KEYS)
    | BOOL_PROPERTY_KEYS
    | DURATION_PROPERTY_KEYS
)

_DURATION_UNITS: dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass
class Token:
    """A token from the agent query language."""

    type: TokenType
    value: str
    case_sensitive: bool = False
    position: int = 0
    property_key: str | None = None
    duration_op: str | None = None  # one of <, <=, >, >=, = (DURATION only)
    duration_seconds: int | None = None  # DURATION only


class TokenizerError(Exception):
    """Raised when tokenization fails."""

    def __init__(self, message: str, position: int) -> None:
        self.position = position
        super().__init__(f"{message} at position {position}")


def _skip_whitespace(query: str, pos: int) -> int:
    while pos < len(query) and query[pos] in " \t\r\n":
        pos += 1
    return pos


def _parse_quoted_string(query: str, pos: int) -> tuple[str, int]:
    """Parse a quoted string starting at the opening quote.

    Returns ``(value, position_after_closing_quote)``.
    """
    start_pos = pos
    pos += 1  # opening quote
    chars: list[str] = []
    while pos < len(query):
        ch = query[pos]
        if ch == '"':
            return "".join(chars), pos + 1
        if ch == "\\":
            if pos + 1 >= len(query):
                raise TokenizerError("Unterminated escape sequence", pos)
            nxt = query[pos + 1]
            mapped = {
                "\\": "\\",
                '"': '"',
                "n": "\n",
                "r": "\r",
                "t": "\t",
            }.get(nxt)
            if mapped is None:
                raise TokenizerError(f"Invalid escape sequence: \\{nxt}", pos)
            chars.append(mapped)
            pos += 2
        else:
            chars.append(ch)
            pos += 1
    raise TokenizerError("Unterminated string", start_pos)


def _is_bare_word_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_-"


def _is_property_value_char(ch: str) -> bool:
    return _is_bare_word_char(ch) or ch == "."


def _parse_property_value(query: str, pos: int) -> tuple[str, int]:
    """Parse a property value (bare word or quoted string)."""
    if pos >= len(query):
        raise TokenizerError("Expected property value", pos)
    if query[pos] == '"':
        return _parse_quoted_string(query, pos)
    start = pos
    while pos < len(query) and _is_property_value_char(query[pos]):
        pos += 1
    if pos == start:
        raise TokenizerError("Expected property value", pos)
    return query[start:pos], pos


def _parse_duration_literal(query: str, pos: int) -> tuple[int, int]:
    """Parse ``(\\d+)(s|m|h|d)`` and return ``(seconds, new_pos)``.

    Whole numbers only; single-unit only; no fractional or composite
    literals (``1.5h``, ``1h30m``).
    """
    start = pos
    while pos < len(query) and query[pos].isdigit():
        pos += 1
    if pos == start:
        raise TokenizerError("Expected duration (e.g. 30m, 2h)", start)
    digits = query[start:pos]
    if pos >= len(query) or query[pos] not in _DURATION_UNITS:
        raise TokenizerError("Expected duration unit s|m|h|d (e.g. 30m, 2h)", pos)
    unit = query[pos]
    pos += 1
    # Reject suffix that would make a composite literal: e.g. 1h30m or 5d2.
    if pos < len(query) and (query[pos].isdigit() or query[pos] in _DURATION_UNITS):
        raise TokenizerError(
            "Composite durations (e.g. 1h30m) are not supported; "
            "use 'age>=1h AND age<90m'",
            start,
        )
    return int(digits) * _DURATION_UNITS[unit], pos


def _validate_bool_value(key: str, value: str, position: int) -> str:
    lowered = value.lower()
    if lowered not in ("true", "false"):
        raise TokenizerError(
            f"{key}: only accepts true/false (got {value!r})", position
        )
    return lowered


def _validate_enum_value(key: str, value: str, position: int) -> str:
    allowed = ENUM_PROPERTY_KEYS[key]
    lowered = value.lower()
    if lowered not in allowed:
        raise TokenizerError(
            f"{key}: only accepts {sorted(allowed)} (got {value!r})", position
        )
    return lowered


def _maybe_consume_age_comparator(query: str, pos: int) -> tuple[str, int] | None:
    """If ``query[pos:]`` starts with ``<=``/``>=``/``<``/``>``/``=``/``:``, return op and new pos.

    The colon is treated as the alias ``>=`` at parse time, but we keep it
    distinct in the returned op so callers can preserve the user's intent.
    """
    if pos >= len(query):
        return None
    two = query[pos : pos + 2]
    if two in ("<=", ">="):
        return two, pos + 2
    one = query[pos]
    if one in ("<", ">", "=", ":"):
        return one, pos + 1
    return None


def tokenize(query: str) -> Iterator[Token]:
    """Tokenize an agent query string."""
    pos = 0
    length = len(query)

    while pos < length:
        pos = _skip_whitespace(query, pos)
        if pos >= length:
            break

        char = query[pos]

        # c"..." (case-sensitive) or "..." (case-insensitive) string literal.
        if char == "c" and pos + 1 < length and query[pos + 1] == '"':
            start_pos = pos
            value, pos = _parse_quoted_string(query, pos + 1)
            yield Token(
                type=TokenType.STRING,
                value=value,
                case_sensitive=True,
                position=start_pos,
            )
            continue
        if char == '"':
            start_pos = pos
            value, pos = _parse_quoted_string(query, pos)
            yield Token(
                type=TokenType.STRING,
                value=value,
                case_sensitive=False,
                position=start_pos,
            )
            continue

        # NOT operator: only the bang form here. The full word "NOT" is handled
        # in the alpha-word branch.
        if char == "!":
            yield Token(type=TokenType.NOT, value="!", position=pos)
            pos += 1
            continue

        if char == "(":
            yield Token(type=TokenType.LPAREN, value="(", position=pos)
            pos += 1
            continue
        if char == ")":
            yield Token(type=TokenType.RPAREN, value=")", position=pos)
            pos += 1
            continue

        # Bare word, keyword, or "key:value" / "age<2h" / etc.
        if char.isalpha() or char == "_":
            start = pos
            while pos < length and _is_bare_word_char(query[pos]):
                pos += 1
            word = query[start:pos]
            word_upper = word.upper()
            word_lower = word.lower()

            if word_upper == "AND":
                yield Token(type=TokenType.AND, value=word, position=start)
                continue
            if word_upper == "OR":
                yield Token(type=TokenType.OR, value=word, position=start)
                continue
            if word_upper == "NOT":
                yield Token(type=TokenType.NOT, value=word, position=start)
                continue

            # Age duration comparison: <key><op><duration>
            if word_lower in DURATION_PROPERTY_KEYS:
                op_info = _maybe_consume_age_comparator(query, pos)
                if op_info is None:
                    raise TokenizerError(
                        f"{word_lower}: expected comparator (one of <, <=, >, >=, =, :)",
                        pos,
                    )
                op, pos = op_info
                # ":" is sugar for ">=" ("at least N old")
                effective_op = ">=" if op == ":" else op
                seconds, pos = _parse_duration_literal(query, pos)
                yield Token(
                    type=TokenType.DURATION,
                    value=word_lower,
                    position=start,
                    property_key=word_lower,
                    duration_op=effective_op,
                    duration_seconds=seconds,
                )
                continue

            # property: "key:value"
            if pos < length and query[pos] == ":":
                if word_lower not in VALID_PROPERTY_KEYS:
                    raise TokenizerError(
                        f"Unknown property key: {word} (valid keys: "
                        f"{', '.join(sorted(VALID_PROPERTY_KEYS))})",
                        start,
                    )
                pos += 1  # consume ':'
                # Bare "tag:" with no value matches "any tagged agent" — emit
                # an empty PROPERTY value so the evaluator can dispatch on it.
                if word_lower == "tag" and (pos >= length or query[pos] in " \t\r\n)"):
                    yield Token(
                        type=TokenType.PROPERTY,
                        value="",
                        position=start,
                        property_key="tag",
                    )
                    continue
                value_pos = pos
                value, pos = _parse_property_value(query, pos)
                if word_lower in BOOL_PROPERTY_KEYS:
                    value = _validate_bool_value(word_lower, value, value_pos)
                elif word_lower in ENUM_PROPERTY_KEYS:
                    value = _validate_enum_value(word_lower, value, value_pos)
                yield Token(
                    type=TokenType.PROPERTY,
                    value=value,
                    position=start,
                    property_key=word_lower,
                )
                continue

            # Plain bare word → case-insensitive substring match.
            yield Token(
                type=TokenType.STRING,
                value=word,
                case_sensitive=False,
                position=start,
            )
            continue

        # Free-floating comparison operators (outside an "age..." context) are
        # rejected so we don't accidentally promise a global comparator syntax.
        if char in "<>=":
            raise TokenizerError(
                f"Unexpected '{char}' (comparison operators are only valid "
                "after 'age')",
                pos,
            )

        raise TokenizerError(f"Unexpected character: {char}", pos)

    yield Token(type=TokenType.EOF, value="", position=pos)

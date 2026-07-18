"""Parser for the deliberately flat notification-gate option query language.

Grammar::

    query  := branch ( OR branch )*
    branch := option ( AND option )* | "(" option ( AND option )* ")"
    option := [a-z][a-z0-9_-]*

``AND`` binds more tightly than ``OR``. Parentheses may make an AND branch
explicit, but may not introduce nesting or contain OR expressions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

_OPTION_RE = re.compile(r"[a-z][a-z0-9_-]*")


class GateQueryError(ValueError):
    """A positional option-query diagnostic."""

    def __init__(self, message: str, position: int = 0) -> None:
        self.position = position
        super().__init__(f"{message} (at position {position})")


@dataclass(frozen=True)
class ParsedGateQuery:
    """Canonical query text and its ordered normalized branches."""

    query: str
    branches: tuple[tuple[str, ...], ...]


class _TokenKind(Enum):
    OPTION = auto()
    AND = auto()
    OR = auto()
    LPAREN = auto()
    RPAREN = auto()
    EOF = auto()


@dataclass(frozen=True)
class _Token:
    kind: _TokenKind
    value: str
    position: int


def parse_gate_query(value: object) -> ParsedGateQuery:
    """Parse *value* and return canonical text plus normalized branches."""
    if not isinstance(value, str):
        raise GateQueryError("Query must be a string", 0)
    tokens = _tokenize(value)
    parser = _Parser(tokens)
    branches = parser.parse()
    canonical = " OR ".join(
        branch[0] if len(branch) == 1 else f"({' AND '.join(branch)})"
        for branch in branches
    )
    return ParsedGateQuery(query=canonical, branches=branches)


def _tokenize(query: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    position = 0
    while position < len(query):
        character = query[position]
        if character.isspace():
            position += 1
            continue
        if character == "(":
            tokens.append(_Token(_TokenKind.LPAREN, character, position))
            position += 1
            continue
        if character == ")":
            tokens.append(_Token(_TokenKind.RPAREN, character, position))
            position += 1
            continue
        if query.startswith("AND", position) and _keyword_boundary(query, position + 3):
            tokens.append(_Token(_TokenKind.AND, "AND", position))
            position += 3
            continue
        if query.startswith("OR", position) and _keyword_boundary(query, position + 2):
            tokens.append(_Token(_TokenKind.OR, "OR", position))
            position += 2
            continue
        match = _OPTION_RE.match(query, position)
        if match is not None:
            option_id = match.group(0)
            tokens.append(_Token(_TokenKind.OPTION, option_id, position))
            position = match.end()
            continue
        raise GateQueryError(f"Unexpected character {character!r}", position)
    tokens.append(_Token(_TokenKind.EOF, "", len(query)))
    return tuple(tokens)


def _keyword_boundary(query: str, position: int) -> bool:
    return position == len(query) or not (
        query[position].isascii()
        and (query[position].isalnum() or query[position] in "_-")
    )


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...]) -> None:
        self._tokens = tokens
        self._index = 0
        self._seen: dict[str, int] = {}

    @property
    def _current(self) -> _Token:
        return self._tokens[self._index]

    def _advance(self) -> _Token:
        token = self._current
        self._index += 1
        return token

    def parse(self) -> tuple[tuple[str, ...], ...]:
        if self._current.kind is _TokenKind.EOF:
            raise GateQueryError("Query must contain at least one option", 0)
        branches = [self._parse_branch()]
        while self._current.kind is _TokenKind.OR:
            self._advance()
            if self._current.kind is _TokenKind.EOF:
                raise GateQueryError(
                    "Expected an option after OR", self._current.position
                )
            branches.append(self._parse_branch())
        if self._current.kind is not _TokenKind.EOF:
            token = self._current
            if token.kind is _TokenKind.RPAREN:
                message = "Unexpected closing parenthesis"
            elif token.kind is _TokenKind.LPAREN:
                message = "Nested or adjacent parentheses are not allowed"
            else:
                message = f"Expected OR, got {token.value or token.kind.name}"
            raise GateQueryError(message, token.position)
        return tuple(branches)

    def _parse_branch(self) -> tuple[str, ...]:
        parenthesized = self._current.kind is _TokenKind.LPAREN
        opening = self._advance() if parenthesized else None
        if self._current.kind is not _TokenKind.OPTION:
            token = self._current
            message = (
                "Parenthesized branch must contain at least one option"
                if parenthesized and token.kind is _TokenKind.RPAREN
                else "Expected an option"
            )
            raise GateQueryError(message, token.position)
        options = [self._parse_option()]
        while self._current.kind is _TokenKind.AND:
            self._advance()
            if self._current.kind is not _TokenKind.OPTION:
                raise GateQueryError(
                    "Expected an option after AND", self._current.position
                )
            options.append(self._parse_option())
        if parenthesized:
            if self._current.kind is not _TokenKind.RPAREN:
                token = self._current
                if token.kind is _TokenKind.OR:
                    message = "OR may not appear inside a parenthesized branch"
                elif token.kind is _TokenKind.LPAREN:
                    message = "Nested parentheses are not allowed"
                else:
                    message = "Expected a closing parenthesis"
                raise GateQueryError(message, token.position)
            self._advance()
        elif self._current.kind is _TokenKind.RPAREN:
            assert opening is None
            raise GateQueryError(
                "Unexpected closing parenthesis", self._current.position
            )
        return tuple(options)

    def _parse_option(self) -> str:
        token = self._advance()
        previous = self._seen.get(token.value)
        if previous is not None:
            raise GateQueryError(
                f"Option {token.value!r} appears more than once; first seen at position {previous}",
                token.position,
            )
        self._seen[token.value] = token.position
        return token.value


__all__ = ["GateQueryError", "ParsedGateQuery", "parse_gate_query"]

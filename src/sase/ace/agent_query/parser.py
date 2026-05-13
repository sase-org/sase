"""Parser for the agent query language.

Grammar (EBNF):

    query        = ws?, or_expr, ws? ;
    or_expr      = and_expr, { ws, "OR",  ws, and_expr } ;
    and_expr     = unary_expr, { [ws, "AND"], ws, unary_expr } ;
    unary_expr   = { ("!" | "NOT") }, primary ;
    primary      = string | property | duration | "(", or_expr, ")" ;
    string       = bare_word | [c], '"', { string_char }, '"' ;
    bare_word    = (letter | "_"), { letter | digit | "_" | "-" } ;
    property     = property_key, ":", property_value ;
    duration     = "age", ("<" | "<=" | ">" | ">=" | "=" | ":"),
                   digit+, ("s" | "m" | "h" | "d") ;

Property values use the bare-word character set plus ``.`` so dotted tags such
as ``tag:sase-42.3`` do not require quotes.

Precedence (tightest to loosest):
    1. NOT  (! or NOT)
    2. AND  (explicit or implicit via juxtaposition)
    3. OR
    Parentheses override precedence.

The set of valid property keys is policed by the tokenizer; see
:data:`sase.ace.agent_query.tokenizer.VALID_PROPERTY_KEYS`.
"""

from .tokenizer import Token, TokenizerError, TokenType, tokenize
from .types import (
    AndExpr,
    DurationCompare,
    DurationOp,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)


class AgentQueryParseError(Exception):
    """Raised when parsing the agent query fails."""

    def __init__(self, message: str, position: int = 0) -> None:
        self.position = position
        super().__init__(f"{message} (at position {position})")


class _Parser:
    """Recursive descent parser for the agent query language."""

    def __init__(self, query: str) -> None:
        self.query = query
        try:
            self.tokens = list(tokenize(query))
        except TokenizerError as e:
            raise AgentQueryParseError(str(e), e.position) from e
        self.pos = 0

    def _current(self) -> Token:
        if self.pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        token = self._current()
        self.pos += 1
        return token

    def _expect(self, token_type: TokenType) -> Token:
        token = self._current()
        if token.type != token_type:
            raise AgentQueryParseError(
                f"Expected {token_type.name}, got {token.type.name}",
                token.position,
            )
        return self._advance()

    def _check(self, token_type: TokenType) -> bool:
        return self._current().type == token_type

    def parse(self) -> QueryExpr:
        if self._check(TokenType.EOF):
            raise AgentQueryParseError("Empty query", 0)

        expr = self._parse_or_expr()

        if not self._check(TokenType.EOF):
            token = self._current()
            raise AgentQueryParseError(
                f"Unexpected token: {token.value or token.type.name}",
                token.position,
            )
        return expr

    def _parse_or_expr(self) -> QueryExpr:
        left = self._parse_and_expr()
        operands: list[QueryExpr] = [left]
        while self._check(TokenType.OR):
            self._advance()
            operands.append(self._parse_and_expr())
        if len(operands) == 1:
            return operands[0]
        return OrExpr(operands=operands)

    def _can_start_unary(self) -> bool:
        return self._current().type in (
            TokenType.STRING,
            TokenType.PROPERTY,
            TokenType.DURATION,
            TokenType.NOT,
            TokenType.LPAREN,
        )

    def _parse_and_expr(self) -> QueryExpr:
        left = self._parse_unary_expr()
        operands: list[QueryExpr] = [left]
        while True:
            if self._check(TokenType.AND):
                self._advance()
                operands.append(self._parse_unary_expr())
            elif self._can_start_unary():
                operands.append(self._parse_unary_expr())
            else:
                break
        if len(operands) == 1:
            return operands[0]
        return AndExpr(operands=operands)

    def _parse_unary_expr(self) -> QueryExpr:
        not_count = 0
        while self._check(TokenType.NOT):
            self._advance()
            not_count += 1
        expr = self._parse_primary()
        for _ in range(not_count):
            expr = NotExpr(operand=expr)
        return expr

    def _parse_primary(self) -> QueryExpr:
        token = self._current()

        if token.type == TokenType.STRING:
            self._advance()
            return StringMatch(value=token.value, case_sensitive=token.case_sensitive)

        if token.type == TokenType.PROPERTY:
            self._advance()
            assert token.property_key is not None
            return PropertyMatch(key=token.property_key, value=token.value)

        if token.type == TokenType.DURATION:
            self._advance()
            assert token.property_key is not None
            assert token.duration_op is not None
            assert token.duration_seconds is not None
            op: DurationOp = token.duration_op  # type: ignore[assignment]
            return DurationCompare(
                key=token.property_key,
                op=op,
                seconds=token.duration_seconds,
            )

        if token.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_or_expr()
            self._expect(TokenType.RPAREN)
            return expr

        raise AgentQueryParseError(
            f"Expected string, property, or '(', got {token.value or token.type.name}",
            token.position,
        )


def parse_agent_query(query: str) -> QueryExpr:
    """Parse an agent query string into an AST.

    Examples:
        >>> parse_agent_query("status:failed")
        PropertyMatch(key='status', value='failed')
        >>> parse_agent_query("age>2h")
        DurationCompare(key='age', op='>', seconds=7200)
    """
    return _Parser(query).parse()

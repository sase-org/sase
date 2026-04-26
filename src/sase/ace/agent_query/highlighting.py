"""Syntax-highlighting tokenization for the agent query language.

Mirrors :mod:`sase.ace.query.highlighting` but for the closed property-key
allowlist defined in :mod:`sase.ace.agent_query.tokenizer`. Used by the
filter modal so the editor highlights the same constructs the parser
accepts (and nothing extra).

The output is a list of ``(token, token_type)`` tuples; the styles dict
:data:`AGENT_QUERY_TOKEN_STYLES` maps token types to Rich style strings.
Token types intentionally overlap with the changespec query module where
the meaning is identical (``keyword``, ``negation``, ``paren``,
``quoted``, ``term``, ``property_key``, ``property_value``,
``whitespace``) plus ``duration_op`` / ``duration_value`` for the
``age``-comparison family.
"""

from __future__ import annotations

from .tokenizer import VALID_PROPERTY_KEYS


def _is_bare_word_char(char: str) -> bool:
    return char.isalnum() or char in "_-"


def tokenize_agent_query_for_display(query: str) -> list[tuple[str, str]]:
    """Tokenize an agent query string for syntax highlighting.

    Best-effort: emits raw spans for inputs the parser would reject so the
    editor still renders something while the user is mid-keystroke.
    """
    tokens: list[tuple[str, str]] = []
    i = 0

    while i < len(query):
        if query[i].isspace():
            start = i
            while i < len(query) and query[i].isspace():
                i += 1
            tokens.append((query[start:i], "whitespace"))
            continue

        if query[i] in "()":
            tokens.append((query[i], "paren"))
            i += 1
            continue

        if query[i] == "!":
            tokens.append(("!", "negation"))
            i += 1
            continue

        # Quoted strings (with optional case-sensitive prefix).
        if query[i] == '"' or (
            query[i] == "c" and i + 1 < len(query) and query[i + 1] == '"'
        ):
            start = i
            if query[i] == "c":
                i += 1
            i += 1  # opening quote
            while i < len(query) and query[i] != '"':
                if query[i] == "\\" and i + 1 < len(query):
                    i += 2
                else:
                    i += 1
            if i < len(query):
                i += 1  # closing quote
            tokens.append((query[start:i], "quoted"))
            continue

        if query[i].isalpha() or query[i] == "_":
            start = i
            while i < len(query) and _is_bare_word_char(query[i]):
                i += 1
            word = query[start:i]
            word_upper = word.upper()
            word_lower = word.lower()

            if word_upper in ("AND", "OR", "NOT"):
                tokens.append((word, "keyword"))
                continue

            # age<...>: emit property_key + duration_op + duration_value.
            if word_lower == "age" and i < len(query) and query[i] in "<>=:":
                tokens.append((word, "property_key"))
                op_start = i
                if query[i : i + 2] in ("<=", ">="):
                    i += 2
                else:
                    i += 1
                tokens.append((query[op_start:i], "duration_op"))
                value_start = i
                while i < len(query) and query[i].isdigit():
                    i += 1
                if i < len(query) and query[i] in "smhd":
                    i += 1
                if i > value_start:
                    tokens.append((query[value_start:i], "duration_value"))
                continue

            # key:value
            if i < len(query) and query[i] == ":" and word_lower in VALID_PROPERTY_KEYS:
                tokens.append((word + ":", "property_key"))
                i += 1
                if i < len(query) and query[i] == '"':
                    v_start = i
                    i += 1
                    while i < len(query) and query[i] != '"':
                        if query[i] == "\\" and i + 1 < len(query):
                            i += 2
                        else:
                            i += 1
                    if i < len(query):
                        i += 1
                    tokens.append((query[v_start:i], "property_value"))
                elif i < len(query) and _is_bare_word_char(query[i]):
                    v_start = i
                    while i < len(query) and _is_bare_word_char(query[i]):
                        i += 1
                    tokens.append((query[v_start:i], "property_value"))
                continue

            tokens.append((word, "term"))
            continue

        # Bare comparison operators outside an age-context — emit so the
        # editor doesn't swallow them silently.
        if query[i] in "<>=":
            start = i
            if query[i : i + 2] in ("<=", ">="):
                i += 2
            else:
                i += 1
            tokens.append((query[start:i], "duration_op"))
            continue

        start = i
        while i < len(query) and not query[i].isspace() and query[i] not in '()!"':
            i += 1
        if i > start:
            tokens.append((query[start:i], "term"))
        else:
            tokens.append((query[i], "term"))
            i += 1

    return tokens


# Token type → Rich style. Mirrors the changespec-query palette where the
# token types overlap; ``duration_op`` / ``duration_value`` are the new
# entries unique to this language.
AGENT_QUERY_TOKEN_STYLES: dict[str, str] = {
    "keyword": "bold #87AFFF",
    "negation": "bold #FF5F5F",
    "quoted": "#808080",
    "term": "#00D7AF",
    "paren": "bold #FFFFFF",
    "property_key": "bold #87D7FF",
    "property_value": "#D7AF5F",
    "duration_op": "bold #FFAF87",
    "duration_value": "#D7AF5F",
    "whitespace": "",
}

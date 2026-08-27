"""Textual key canonicalization, display names, and validation."""

# Reserved spelling that leaves an app action configured but unbound.
UNBOUND_KEY = "unbound"

# Textual special key names -> display characters.
_KEY_DISPLAY: dict[str, str] = {
    "full_stop": ".",
    "dollar_sign": "$",
    "exclamation_mark": "!",
    "percent_sign": "%",
    "comma": ",",
    "less_than_sign": "<",
    "greater_than_sign": ">",
    "circumflex_accent": "^",
    "underscore": "_",
    "number_sign": "#",
    "right_square_bracket": "]",
    "left_square_bracket": "[",
    "right_curly_bracket": "}",
    "left_curly_bracket": "{",
    "right_parenthesis": ")",
    "left_parenthesis": "(",
    "equals_sign": "=",
    "minus": "-",
    "question_mark": "?",
    "apostrophe": "'",
    "grave_accent": "`",
    "slash": "/",
    "asterisk": "*",
    "at": "@",
    "plus": "+",
    "space": "Space",
    "tab": "Tab",
    "shift+tab": "Shift+Tab",
    "enter": "Enter",
    "tilde": "~",
    "semicolon": ";",
    "colon": ":",
}

# Known Textual named keys (beyond what's in _KEY_DISPLAY).
_NAMED_KEYS: set[str] = {
    "escape",
    "enter",
    "tab",
    "backspace",
    "delete",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "pageup",
    "pagedown",
    "insert",
    *(f"f{n}" for n in range(1, 25)),
}

_CTRL_SPACE_KEY = "ctrl+@"
_KEY_ALIASES: dict[str, str] = {
    "ctrl+space": _CTRL_SPACE_KEY,
    "ctrl+at": _CTRL_SPACE_KEY,
    # Textual normalizes the printable ``+`` key to the name ``plus``; accept
    # the raw glyph and the Unicode name as friendly config spellings for it.
    "+": "plus",
    "plus_sign": "plus",
    # Textual normalizes the printable ``-`` key to the name ``minus``; accept
    # the raw glyph as a friendly config spelling for it.
    "-": "minus",
    # Textual normalizes the printable ``$`` key to the name ``dollar_sign``.
    "$": "dollar_sign",
}


def split_key_alternatives(key: str) -> tuple[str, ...]:
    """Split a Textual binding string into its comma-separated alternatives."""
    return tuple(part.strip() for part in key.split(","))


def canonicalize_single_key(key: str) -> str:
    """Return the internal Textual key spelling for one configured key."""
    key = key.strip()
    folded = key.casefold()
    if folded == UNBOUND_KEY:
        return UNBOUND_KEY
    return _KEY_ALIASES.get(folded, key)


def canonicalize_key_binding(key: str) -> str:
    """Canonicalize every alternative in a Textual key binding string."""
    return ",".join(
        canonicalize_single_key(alternative)
        for alternative in split_key_alternatives(key)
    )


def normalize_key_binding(key: str) -> str:
    """Normalize whitespace and aliases around comma-separated key alternatives."""
    return canonicalize_key_binding(key)


def _canonical_key_alternatives(key: str) -> tuple[str, ...]:
    """Split and canonicalize a Textual binding string."""
    return tuple(canonicalize_single_key(part) for part in split_key_alternatives(key))


def is_unbound_key(key: str) -> bool:
    """Return True when *key* is the reserved unbound sentinel."""
    return canonicalize_key_binding(key) == UNBOUND_KEY


def _is_valid_single_key(key: str) -> bool:
    """Check whether *key* is a recognised single Textual key name."""
    if not key:
        return False
    if key == UNBOUND_KEY:
        return True
    if key == _CTRL_SPACE_KEY:
        return True
    # Single alphanumeric character.
    if len(key) == 1 and key.isalnum():
        return True
    # Entry in _KEY_DISPLAY (known Textual special names).
    if key in _KEY_DISPLAY:
        return True
    # Known named keys.
    if key in _NAMED_KEYS:
        return True
    # ctrl+ or shift+ prefix with a valid suffix.
    if key.startswith(("ctrl+", "shift+")):
        suffix = key.split("+", 1)[1]
        return _is_valid_single_key(suffix)
    return False


def is_valid_key(key: str) -> bool:
    """Check whether *key* is a recognised Textual key binding.

    Textual ``Binding`` accepts comma-separated alternatives such as
    ``"colon,semicolon"``. Treat those as a single configurable binding
    whose individual alternatives must each be valid Textual keys.
    """
    alternatives = _canonical_key_alternatives(key)
    return (
        bool(alternatives)
        and len(set(alternatives)) == len(alternatives)
        and all(_is_valid_single_key(alternative) for alternative in alternatives)
    )

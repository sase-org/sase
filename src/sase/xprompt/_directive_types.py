"""Shared types and pattern constants for prompt directive parsing.

Split out from :mod:`sase.xprompt.directives` so the alt/multi-model
splitter and the main extractor can share regex patterns and alias
tables without a circular import.
"""

from dataclasses import dataclass, field

# Pattern to match directive references: %name, %name(, %name:arg, %name:`arg`, %name+
# Mirrors _XPROMPT_PATTERN from processor.py but with % prefix.
# The colon-arg character class is expanded to include # (for xprompt refs in args).
_DIRECTIVE_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"%([a-zA-Z_][a-zA-Z0-9_]*)"  # Group 1: directive name
    r"(?:(\()|:(`[^`]*`|[a-zA-Z0-9_#/.,()-]*[a-zA-Z0-9_#/,()-])|(\+))?"  # Group 2: paren OR Group 3: colon arg OR Group 4: plus
)

# Known directive names
_KNOWN_DIRECTIVES = frozenset(
    {"approve", "edit", "hide", "model", "name", "plan", "repeat", "tag", "wait"}
)

# Directives that allow multiple occurrences (values are collected into a list)
_MULTI_VALUE_DIRECTIVES = frozenset({"wait"})

# Short aliases for directives (alias -> canonical name)
_DIRECTIVE_ALIASES: dict[str, str] = {
    "a": "approve",
    "e": "edit",
    "h": "hide",
    "m": "model",
    "n": "name",
    "r": "repeat",
    "p": "plan",
    "t": "tag",
    "w": "wait",
}


@dataclass
class PromptDirectives:
    """Parsed prompt directives that modify runner behavior.

    Attributes:
        model: Model override string, or None to use the default.
        name: Agent name assigned via %name directive, or None.
        wait: List of agent names to wait for via %wait directives.
    """

    approve: bool = False
    edit: bool = False
    hide: bool = False
    model: str | None = None
    name: str | None = None
    name_explicit: bool = False
    plan: bool = False
    repeat_count: int | None = None
    tag: str | None = None
    wait: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None

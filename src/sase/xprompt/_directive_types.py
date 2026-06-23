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
    r"(?:(\()|:(`[^`]*`|[!a-zA-Z0-9_#/.,()@-]*[a-zA-Z0-9_#/,()@-])|(\+))?"  # Group 2: paren OR Group 3: colon arg OR Group 4: plus
)

# Known directive names
_KNOWN_DIRECTIVES = frozenset(
    {
        "approve",
        "edit",
        "effort",
        "epic",
        "hide",
        "model",
        "name",
        "group",
        "repeat",
        "time",
        "wait",
    }
)

# Directives that allow multiple occurrences (values are collected into a list)
_MULTI_VALUE_DIRECTIVES = frozenset({"time", "wait"})

# Short aliases for directives (alias -> canonical name)
_DIRECTIVE_ALIASES: dict[str, str] = {
    "a": "approve",
    "e": "edit",
    "g": "group",
    "h": "hide",
    "m": "model",
    "n": "name",
    "r": "repeat",
    "t": "time",
    "w": "wait",
}


@dataclass
class PromptDirectives:
    """Parsed prompt directives that modify runner behavior.

    Attributes:
        model: Model override string, or None to use the default.
        reasoning_effort: Reasoning-effort level requested via the ``%effort``
            directive or a ``%model:<model>@<effort>`` suffix, or None when
            none was given. The public directive/suffix spell it ``effort``;
            the stored/threaded field is ``reasoning_effort`` everywhere.
        name: Agent name assigned via %name directive, or None.
        wait: List of agent names to wait for via %wait directives.
    """

    approve: bool = False
    edit: bool = False
    epic: bool = False
    hide: bool = False
    model: str | None = None
    reasoning_effort: str | None = None
    name: str | None = None
    name_explicit: bool = False
    name_force_reuse: bool = False
    name_template: str | None = None
    name_template_base: str | None = None
    name_indexed_template: bool = False
    name_indexed_base: str | None = None
    repeat_count: int | None = None
    # Populated by the user-facing %group directive (alias %g). The internal
    # field name remains `tag` because the persisted concept (agent_tags.json,
    # ACE grouping UI, sase agent tag CLI) still uses "tag".
    tag: str | None = None
    wait: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None

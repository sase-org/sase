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
        "auto",
        "edit",
        "effort",
        "hide",
        "model",
        "name",
        "group",
        "repeat",
        "wait",
    }
)

# Directives that allow multiple occurrences (values are collected into a list)
_MULTI_VALUE_DIRECTIVES = frozenset({"wait"})

# Ordered valid values for the %auto/%a directive. Kept here so parser
# validation and editor completion cannot drift.
AUTO_MODES_ORDERED: tuple[str, ...] = ("plan", "tale", "epic")
AUTO_MODES: frozenset[str] = frozenset(AUTO_MODES_ORDERED)

# Removed directive spellings that should raise targeted migration errors.
_DEPRECATED_DIRECTIVES = frozenset({"time"})

# Short aliases for directives (alias -> canonical name). ``%auto`` is the
# unified plan auto-approval directive; ``%a`` is its advertised alias.
_DIRECTIVE_ALIASES: dict[str, str] = {
    "a": "auto",
    "e": "edit",
    "g": "group",
    "h": "hide",
    "m": "model",
    "n": "name",
    "r": "repeat",
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
        wait: List of agent names to wait for via positional %wait arguments.
        wait_duration: Duration in seconds from the %wait(time=...) keyword.
        wait_until: Absolute target datetime from the %wait(time=...) keyword.
        auto_mode: Auto-approval mode from ``%auto``/``%a``: ``"plan"``,
            ``"tale"``, ``"epic"``, or None when no auto-approval directive
            was present.
    """

    auto_mode: str | None = None
    edit: bool = False
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

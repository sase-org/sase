"""Shared types and pattern constants for prompt directive parsing.

Split out from :mod:`sase.xprompt.directives` so the alt/multi-model
splitter and the main extractor can share regex patterns and alias
tables without a circular import.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

# Pattern to match directive references: %name, %name(, %name:arg, %name:`arg`, %name+
# Mirrors _XPROMPT_PATTERN from processor.py but with % prefix.
# The colon-arg character class is expanded to include # (for xprompt refs in args).
_DIRECTIVE_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"%([a-zA-Z_][a-zA-Z0-9_]*)"  # Group 1: directive name
    r"(?:(\()|:(`[^`]*`|[!a-zA-Z0-9_#/.,()@=-]*[a-zA-Z0-9_#/,()@=-])|(\+))?"  # Group 2: paren OR Group 3: colon arg OR Group 4: plus
)

# Known directive names
_KNOWN_DIRECTIVES = frozenset(
    {
        "auto",
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

# Compatibility suggestions for the %auto/%a directive. The parser retains
# arbitrary raw arguments; the adapter that opens a gate owns validation.
AUTO_MODES_ORDERED: tuple[str, ...] = ("plan", "tale", "epic")
AUTO_MODES: frozenset[str] = frozenset(AUTO_MODES_ORDERED)

# Removed directive spellings that should raise targeted migration errors when
# they reach the runtime parser. ``%edit`` became an editor-only ` @` review
# marker; see ``strip_editor_review_markers``. ``%e`` is no longer an ``%edit``
# alias — it now resolves to ``%effort`` (see ``_DIRECTIVE_ALIASES`` below).
_DEPRECATED_DIRECTIVE_MESSAGES: dict[str, str] = {
    "time": (
        "The '%time' directive has been removed; use #t:<time> "
        "or %wait(time=<time>) instead."
    ),
    "edit": (
        "The '%edit' directive has been removed; from an editor, put ' @' at "
        "the end of any line to reload the prompt for review."
    ),
}
_DEPRECATED_DIRECTIVES = frozenset(_DEPRECATED_DIRECTIVE_MESSAGES)

# Short aliases for directives (alias -> canonical name). ``%auto`` is the
# unified plan auto-approval directive; ``%a`` is its advertised alias. ``%e``
# is the advertised alias for ``%effort``: it sets ``reasoning_effort`` exactly
# like ``%effort`` and is canonicalized to ``effort`` for duplicate/conflict
# validation, prompt cleanup, and completion. (``%edit`` remains the migration
# surface for old editor buffers; it is still in ``_DEPRECATED_DIRECTIVES``.)
_DIRECTIVE_ALIASES: dict[str, str] = {
    "a": "auto",
    "e": "effort",
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
        model_alias_overrides: Launch-family-scoped model alias targets from
            keyword arguments on the ``%model`` directive.
        reasoning_effort: Reasoning-effort level requested via the ``%effort``
            directive or a ``%model:<model>@<effort>`` suffix, or None when
            none was given. The public directive/suffix spell it ``effort``;
            the stored/threaded field is ``reasoning_effort`` everywhere.
        name: Agent name assigned via %name directive, or None.
        wait: List of agent names to wait for via positional %wait arguments.
        wait_duration: Duration in seconds from the %wait(time=...) keyword.
        wait_until: Absolute target datetime from the %wait(time=...) keyword.
        wait_runners: Existing-runner threshold from the
            %wait(runners=...) keyword.
        auto_mode: Compatibility rendering of the raw ``%auto`` argument;
            bare ``%auto`` is ``"plan"`` and absence is None.
        auto_enabled: Whether ``%auto``/``%a`` was present.
        auto_argument: The optional raw argument, validated later by the gate
            adapter that owns the interaction kind.
    """

    auto_mode: str | None = None
    auto_enabled: bool = False
    auto_argument: str | None = None
    hide: bool = False
    model: str | None = None
    model_alias_overrides: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    reasoning_effort: str | None = None
    name: str | None = None
    name_explicit: bool = False
    name_force_reuse: bool = False
    family_attach_parent: str | None = None
    family_attach_suffix: str | None = None
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
    wait_runners: int | None = None

    def __post_init__(self) -> None:
        self.model_alias_overrides = MappingProxyType(dict(self.model_alias_overrides))

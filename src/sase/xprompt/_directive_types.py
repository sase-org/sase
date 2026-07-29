"""Shared types and pattern constants for prompt directive parsing.

Split out from :mod:`sase.xprompt.directives` so the alt/multi-model
splitter and the main extractor can share regex patterns and alias
tables without a circular import.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

# A keyed `{@<id>}` / `{@<id>!}` agent-name marker. Colon arguments admit this
# as an indivisible unit rather than adding `{}` to their character classes: a
# loose `}` would let `%m:#codex}` swallow the closing brace of the enclosing
# `%{a | b}` fan-out group.
KEY_MARKER_PATTERN = r"\{@[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*!?\}"

# Pattern to match directive references: %id, %id(, %id:arg, %id:`arg`, %id+
# Mirrors _XPROMPT_PATTERN from processor.py but with % prefix.
# The colon-arg character class is expanded to include # (for xprompt refs in args).
_DIRECTIVE_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"%([a-zA-Z_][a-zA-Z0-9_]*)"  # Group 1: directive name
    r"(?:(\()|:(`[^`]*`|"  # Group 2: paren OR Group 3: colon arg
    rf"(?:{KEY_MARKER_PATTERN}|[!a-zA-Z0-9_#/.,()@=-])*"  # arg body
    rf"(?:{KEY_MARKER_PATTERN}|[a-zA-Z0-9_#/,()@=-])"  # arg must not end in . or !
    r")|(\+))?"  # Group 4: plus
)

# Known directive names
_KNOWN_DIRECTIVES = frozenset(
    {
        "auto",
        "clan",
        "effort",
        "hide",
        "model",
        "id",
        "repeat",
        "wait",
    }
)

# Directives that allow multiple occurrences (values are collected into a list)
_MULTI_VALUE_DIRECTIVES = frozenset({"wait"})

# Compatibility argument suggestions for the %auto/%a directive. The parser
# retains arbitrary raw arguments; the adapter that opens a gate owns validation.
AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS: tuple[str, ...] = (
    "plan",
    "tale",
    "epic",
)

# Removed directive spellings that should raise targeted migration errors when
# they reach the runtime parser. ``%edit`` became an editor-only ` @` review
# marker; see ``strip_editor_review_markers``. ``%e`` is no longer an ``%edit``
# alias — it now resolves to ``%effort`` (see ``_DIRECTIVE_ALIASES`` below).
_DEPRECATED_DIRECTIVE_MESSAGES: dict[str, str] = {
    "name": (
        "The '%name'/'%n' directive has been renamed; use %id/%i, and "
        "%id(<id>, clan=<clan>) to join a clan."
    ),
    "time": (
        "The '%time' directive has been removed; use #t:<time> "
        "or %wait(time=<time>) instead."
    ),
    "edit": (
        "The '%edit' directive has been removed; from an editor, put ' @' at "
        "the end of any line to reload the prompt for review."
    ),
    "tribe": (
        "The '%tribe'/'%t' directive has been removed; use "
        "%id(tribe=<tribe>) or the #tribe xprompt for an auto-named agent, "
        "%id(<id>, tribe=<tribe>) for an explicitly named agent, or "
        "%clan(<clan>, tribe=<tribe>) for a clan."
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
    "c": "clan",
    "e": "effort",
    "h": "hide",
    "i": "id",
    "m": "model",
    "n": "name",
    "r": "repeat",
    "t": "tribe",
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
        name: Agent name assigned via the %id directive, or None. The field
            remains ``name`` because it stores the resulting full agent name.
        bead_id: Bead associated with this generic launch via ``%id(bead=...)``,
            or None.
        clan: Clan name or name template requested via ``%clan``/``%c`` or
            the ``clan=`` keyword on ``%id``, or None when no clan membership
            was requested.
        clan_declared: Whether clan membership came from an explicit
            ``%clan`` declaration rather than the ``clan=`` join form.
        clan_tribe: Tribe declared through ``%clan(..., tribe=...)``, or None.
        clan_summary: Rich-markup summary declared through
            ``%clan(..., summary=...)`` or the ``::`` shorthand, or None.
        clan_summary_script: Executable summary producer declared through
            ``%clan(..., summary_script=...)``, or None.
        tribe: Standalone tribe declared through the ``tribe=`` keyword on
            ``%id``, or None.
        wait: List of agent names to wait for via positional %wait arguments.
        wait_beads: Ordered, deduplicated bead IDs from %wait(bead=...) keywords.
        wait_duration: Duration in seconds from the %wait(time=...) keyword.
        wait_until: Absolute target datetime from the %wait(time=...) keyword.
        wait_runners: Existing-runner threshold from the
            %wait(runners=...) keyword.
        wait_priority: Runner-slot queue priority from the
            %wait(priority=...) keyword. Lower values start first.
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
    bead_id: str | None = None
    name_explicit: bool = False
    name_force_reuse: bool = False
    clan: str | None = None
    clan_declared: bool = False
    clan_tribe: str | None = None
    clan_summary: str | None = None
    clan_summary_script: str | None = None
    family_attach_parent: str | None = None
    family_attach_suffix: str | None = None
    name_template: str | None = None
    name_template_base: str | None = None
    name_indexed_template: bool = False
    name_indexed_base: str | None = None
    repeat_count: int | None = None
    tribe: str | None = None
    wait: list[str] = field(default_factory=list)
    wait_beads: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    wait_runners: int | None = None
    wait_priority: int | None = None

    def __post_init__(self) -> None:
        self.model_alias_overrides = MappingProxyType(dict(self.model_alias_overrides))

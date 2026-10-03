"""Lexical parsing for macro and workflow references."""

from dataclasses import dataclass
from enum import Enum
import re

from ._parsing_args import (
    double_colon_text_start,
    find_matching_paren_for_args,
    parse_workflow_reference,
)
from ._parsing_shorthand import find_double_colon_text_end, find_shorthand_text_end


MACRO_REFERENCE_LEADING_CONTEXT = r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
"""Regex fragment for positions where an xprompt reference may start."""

MACRO_REFERENCE_MARKER_FRAGMENT = r"(?P<marker>#!|#)"
"""Regex fragment for inline (``#``) and standalone (``#!``) markers."""

MACRO_REFERENCE_NAME_FRAGMENT = (
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
)
"""Regex fragment for an xprompt/workflow name."""

MACRO_REFERENCE_HITL_SUFFIX_FRAGMENT = r"(?P<hitl>!!|\?\?)?"
"""Regex fragment for an optional HITL override suffix."""

MACRO_REFERENCE_ARGUMENT_FRAGMENT = (
    r"(?:(?P<open_paren>\()|:"
    r"(?P<colon_arg>`[^`]*`|\$\([^)]*\)|\{\{[^}]*\}\}|\{[^}]*\}|[a-zA-Z0-9_.~,+/@-]*[a-zA-Z0-9_~,+/@-])"
    r"|(?P<plus>\+))?"
)
"""Regex fragment for the first token of supported argument syntaxes."""

MACRO_REFERENCE_PATTERN = re.compile(
    MACRO_REFERENCE_LEADING_CONTEXT
    + MACRO_REFERENCE_MARKER_FRAGMENT
    + MACRO_REFERENCE_NAME_FRAGMENT
    + MACRO_REFERENCE_HITL_SUFFIX_FRAGMENT
    + MACRO_REFERENCE_ARGUMENT_FRAGMENT,
    re.MULTILINE,
)
"""Shared lexical matcher for xprompt and standalone workflow references."""


class MacroReferenceMarker(Enum):
    """The marker used to introduce a macro/workflow reference."""

    INLINE = "#"
    STANDALONE = "#!"


class MacroReferenceArgKind(Enum):
    """The argument syntax attached to a macro/workflow reference."""

    NONE = "none"
    PAREN = "paren"
    COLON = "colon"
    COLON_SHORTHAND = "colon_shorthand"
    DOUBLE_COLON_SHORTHAND = "double_colon_shorthand"
    PLUS = "plus"


@dataclass(frozen=True)
class MacroReference:
    """A parsed macro/workflow reference in prompt text."""

    marker: MacroReferenceMarker
    name: str
    start: int
    end: int
    raw: str
    arg_kind: MacroReferenceArgKind = MacroReferenceArgKind.NONE
    argument_source: str = ""
    hitl_override: bool | None = None
    shorthand_text_start: int | None = None
    """Offset where ``: ``/``:: `` free-text argument content begins, if any."""

    @property
    def is_standalone_marker(self) -> bool:
        """Return True when the reference used the standalone ``#!`` marker."""
        return self.marker is MacroReferenceMarker.STANDALONE

    @property
    def reference_body(self) -> str:
        """Return the normalized reference without marker or HITL suffix."""
        return f"{self.name}{self.argument_source}"

    def parse_arguments(self) -> tuple[list[str], dict[str, str]]:
        """Parse this reference's argument payload using workflow arg rules."""
        if self.arg_kind is MacroReferenceArgKind.DOUBLE_COLON_SHORTHAND:
            if self.shorthand_text_start is not None:
                payload_start = self.shorthand_text_start - (
                    self.end - len(self.argument_source)
                )
                return [self.argument_source[payload_start:]], {}
            return [self.argument_source[3:]], {}
        if self.arg_kind is MacroReferenceArgKind.COLON_SHORTHAND:
            return [self.argument_source[2:]], {}

        _name, positional_args, named_args = parse_workflow_reference(
            self.reference_body
        )
        return positional_args, named_args


def _hitl_override_from_suffix(suffix: str | None) -> bool | None:
    if suffix == "!!":
        return True
    if suffix == "??":
        return False
    return None


def _reference_arg_kind_from_match(
    prompt: str, match: re.Match[str], end: int
) -> MacroReferenceArgKind:
    if match.group("open_paren") is not None:
        return MacroReferenceArgKind.PAREN
    if match.group("colon_arg") is not None:
        return MacroReferenceArgKind.COLON
    if match.group("plus") is not None:
        return MacroReferenceArgKind.PLUS

    if end != match.end() and double_colon_text_start(prompt, match.end()) is not None:
        return MacroReferenceArgKind.DOUBLE_COLON_SHORTHAND
    after_match = prompt[match.end() : end]
    if after_match.startswith(": "):
        return MacroReferenceArgKind.COLON_SHORTHAND
    return MacroReferenceArgKind.NONE


def _reference_span(prompt: str, match: re.Match[str]) -> tuple[int, int | None]:
    """Return ``(end, shorthand_text_start)`` for a reference match."""
    if match.group("open_paren") is not None:
        paren_start = match.end("open_paren") - 1
        paren_end = find_matching_paren_for_args(prompt, paren_start)
        if paren_end is None:
            return match.end(), None

        end = paren_end + 1
        double_start = double_colon_text_start(prompt, end)
        if double_start is not None:
            return find_double_colon_text_end(prompt, double_start), double_start
        if prompt[end:].startswith(": "):
            return find_shorthand_text_end(prompt, end + 2), end + 2
        after_paren = prompt[end:]
        if after_paren.startswith(":") and len(after_paren) > 1:
            # Avoid eating the second colon of a `::` delimiter here; the
            # double-colon check above already handled valid delimiters.
            if double_colon_text_start(prompt, end) is None:
                return end + 1 + len(after_paren[1:].split(maxsplit=1)[0]), None
            return end, None
        return end, None

    if match.group("colon_arg") is not None or match.group("plus") is not None:
        return match.end(), None

    double_start = double_colon_text_start(prompt, match.end())
    if double_start is not None:
        return find_double_colon_text_end(prompt, double_start), double_start
    if prompt[match.end() :].startswith(": "):
        text_start = match.end() + 2
        return find_shorthand_text_end(prompt, text_start), text_start
    return match.end(), None


def macro_reference_from_match(prompt: str, match: re.Match[str]) -> MacroReference:
    """Build an :class:`MacroReference` from a shared regex match."""
    marker = MacroReferenceMarker(match.group("marker"))
    hitl_suffix = match.group("hitl")
    name_end = match.end("hitl") if hitl_suffix else match.end("name")
    end, shorthand_text_start = _reference_span(prompt, match)
    raw = prompt[match.start() : end]

    return MacroReference(
        marker=marker,
        name=match.group("name").replace("__", "/"),
        start=match.start(),
        end=end,
        raw=raw,
        arg_kind=_reference_arg_kind_from_match(prompt, match, end),
        argument_source=prompt[name_end:end],
        hitl_override=_hitl_override_from_suffix(hitl_suffix),
        shorthand_text_start=shorthand_text_start,
    )


def iter_macro_references(prompt: str) -> list[MacroReference]:
    """Return all lexical macro/workflow references in *prompt*.

    This function intentionally does not protect fenced blocks. Callers that
    need fence-aware behavior should protect or filter the prompt before using
    the shared parser.
    """
    return [
        macro_reference_from_match(prompt, match)
        for match in MACRO_REFERENCE_PATTERN.finditer(prompt)
    ]

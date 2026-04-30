"""Lexical parsing for xprompt and workflow references."""

from dataclasses import dataclass
from enum import Enum
import re

from ._parsing_args import find_matching_paren_for_args, parse_workflow_reference
from ._parsing_shorthand import find_double_colon_text_end, find_shorthand_text_end


XPROMPT_REFERENCE_LEADING_CONTEXT = r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
"""Regex fragment for positions where an xprompt reference may start."""

XPROMPT_REFERENCE_MARKER_FRAGMENT = r"(?P<marker>#!|#)"
"""Regex fragment for inline (``#``) and standalone (``#!``) markers."""

XPROMPT_REFERENCE_NAME_FRAGMENT = (
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
)
"""Regex fragment for an xprompt/workflow name."""

XPROMPT_REFERENCE_HITL_SUFFIX_FRAGMENT = r"(?P<hitl>!!|\?\?)?"
"""Regex fragment for an optional HITL override suffix."""

XPROMPT_REFERENCE_ARGUMENT_FRAGMENT = (
    r"(?:(?P<open_paren>\()|:"
    r"(?P<colon_arg>`[^`]*`|\$\([^)]*\)|\{\{[^}]*\}\}|\{[^}]*\}|[a-zA-Z0-9_.~,/-]*[a-zA-Z0-9_~/-])"
    r"|(?P<plus>\+))?"
)
"""Regex fragment for the first token of supported argument syntaxes."""

XPROMPT_REFERENCE_PATTERN = re.compile(
    XPROMPT_REFERENCE_LEADING_CONTEXT
    + XPROMPT_REFERENCE_MARKER_FRAGMENT
    + XPROMPT_REFERENCE_NAME_FRAGMENT
    + XPROMPT_REFERENCE_HITL_SUFFIX_FRAGMENT
    + XPROMPT_REFERENCE_ARGUMENT_FRAGMENT,
    re.MULTILINE,
)
"""Shared lexical matcher for xprompt and standalone workflow references."""


class XPromptReferenceMarker(Enum):
    """The marker used to introduce an xprompt/workflow reference."""

    INLINE = "#"
    STANDALONE = "#!"


class XPromptReferenceArgKind(Enum):
    """The argument syntax attached to an xprompt/workflow reference."""

    NONE = "none"
    PAREN = "paren"
    COLON = "colon"
    COLON_SHORTHAND = "colon_shorthand"
    DOUBLE_COLON_SHORTHAND = "double_colon_shorthand"
    PLUS = "plus"


@dataclass(frozen=True)
class XPromptReference:
    """A parsed xprompt/workflow reference in prompt text."""

    marker: XPromptReferenceMarker
    name: str
    start: int
    end: int
    raw: str
    arg_kind: XPromptReferenceArgKind = XPromptReferenceArgKind.NONE
    argument_source: str = ""
    hitl_override: bool | None = None

    @property
    def is_standalone_marker(self) -> bool:
        """Return True when the reference used the standalone ``#!`` marker."""
        return self.marker is XPromptReferenceMarker.STANDALONE

    @property
    def reference_body(self) -> str:
        """Return the normalized reference without marker or HITL suffix."""
        return f"{self.name}{self.argument_source}"

    def parse_arguments(self) -> tuple[list[str], dict[str, str]]:
        """Parse this reference's argument payload using workflow arg rules."""
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
) -> XPromptReferenceArgKind:
    if match.group("open_paren") is not None:
        return XPromptReferenceArgKind.PAREN
    if match.group("colon_arg") is not None:
        return XPromptReferenceArgKind.COLON
    if match.group("plus") is not None:
        return XPromptReferenceArgKind.PLUS

    after_match = prompt[match.end() : end]
    if after_match.startswith(":: "):
        return XPromptReferenceArgKind.DOUBLE_COLON_SHORTHAND
    if after_match.startswith(": "):
        return XPromptReferenceArgKind.COLON_SHORTHAND
    return XPromptReferenceArgKind.NONE


def _reference_end(prompt: str, match: re.Match[str]) -> int:
    """Return the semantic end offset for a reference match."""
    if match.group("open_paren") is not None:
        paren_start = match.end("open_paren") - 1
        paren_end = find_matching_paren_for_args(prompt, paren_start)
        if paren_end is None:
            return match.end()

        end = paren_end + 1
        after_paren = prompt[end:]
        if after_paren.startswith(":: "):
            return find_double_colon_text_end(prompt, end + 3)
        if after_paren.startswith(": "):
            return find_shorthand_text_end(prompt, end + 2)
        if after_paren.startswith(":") and len(after_paren) > 1:
            return end + 1 + len(after_paren[1:].split(maxsplit=1)[0])
        return end

    if match.group("colon_arg") is not None or match.group("plus") is not None:
        return match.end()

    after_match = prompt[match.end() :]
    if after_match.startswith(":: "):
        return find_double_colon_text_end(prompt, match.end() + 3)
    if after_match.startswith(": "):
        return find_shorthand_text_end(prompt, match.end() + 2)
    return match.end()


def xprompt_reference_from_match(prompt: str, match: re.Match[str]) -> XPromptReference:
    """Build an :class:`XPromptReference` from a shared regex match."""
    marker = XPromptReferenceMarker(match.group("marker"))
    hitl_suffix = match.group("hitl")
    name_end = match.end("hitl") if hitl_suffix else match.end("name")
    end = _reference_end(prompt, match)
    raw = prompt[match.start() : end]

    return XPromptReference(
        marker=marker,
        name=match.group("name").replace("__", "/"),
        start=match.start(),
        end=end,
        raw=raw,
        arg_kind=_reference_arg_kind_from_match(prompt, match, end),
        argument_source=prompt[name_end:end],
        hitl_override=_hitl_override_from_suffix(hitl_suffix),
    )


def iter_xprompt_references(prompt: str) -> list[XPromptReference]:
    """Return all lexical xprompt/workflow references in *prompt*.

    This function intentionally does not protect fenced blocks. Callers that
    need fence-aware behavior should protect or filter the prompt before using
    the shared parser.
    """
    return [
        xprompt_reference_from_match(prompt, match)
        for match in XPROMPT_REFERENCE_PATTERN.finditer(prompt)
    ]

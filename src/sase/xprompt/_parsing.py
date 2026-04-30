"""Argument parsing, text block processing, and shorthand syntax."""

import re

from . import _parsing_args as _args
from . import _parsing_shorthand as _shorthand
from ._parsing_args import (
    escape_for_xprompt,
    find_matching_paren_for_args,
    parse_args,
    parse_workflow_reference,
    strip_hitl_suffix,
)
from ._parsing_references import (
    XPROMPT_REFERENCE_ARGUMENT_FRAGMENT,
    XPROMPT_REFERENCE_HITL_SUFFIX_FRAGMENT,
    XPROMPT_REFERENCE_LEADING_CONTEXT,
    XPROMPT_REFERENCE_MARKER_FRAGMENT,
    XPROMPT_REFERENCE_NAME_FRAGMENT,
    XPROMPT_REFERENCE_PATTERN,
    XPromptReference,
    XPromptReferenceArgKind,
    XPromptReferenceMarker,
    iter_xprompt_references,
    xprompt_reference_from_match,
)
from ._parsing_shorthand import (
    DOUBLE_COLON_SHORTHAND_PATTERN,
    SHORTHAND_PATTERN,
    find_double_colon_text_end,
    find_shorthand_text_end,
    preprocess_shorthand_syntax,
)


def _parse_named_arg(token: str) -> tuple[str | None, str]:
    """Compatibility wrapper for tests that import the old private helper."""
    return _args._parse_named_arg(token)


def _process_text_block(value: str) -> str:
    """Compatibility wrapper for tests that import the old private helper."""
    return _args._process_text_block(value)


def _format_as_text_block(text: str) -> str:
    """Compatibility wrapper for tests that import the old private helper."""
    return _shorthand._format_as_text_block(text)


def _preprocess_paren_shorthand(prompt: str, xprompt_names: set[str]) -> str:
    """Compatibility wrapper for tests that import the old private helper."""
    return _shorthand._preprocess_paren_shorthand(prompt, xprompt_names)


_VCS_TAG_PATTERN: re.Pattern[str] | None = None
_VCS_UNDERSCORE_NORMALIZER: re.Pattern[str] | None = None


def normalize_vcs_underscore_refs(prompt: str) -> str:
    """Normalize ``#gh_sase`` to ``#gh:sase`` for known VCS workflow names.

    The xprompt and embedded-workflow regex patterns treat ``_`` as part of the
    identifier, so ``#gh_sase`` is parsed as a single name ``gh_sase`` which
    doesn't match any workflow.  Converting the first ``_`` after a known VCS
    prefix to ``:`` lets downstream patterns correctly split the VCS prefix
    from the ref name.
    """
    global _VCS_UNDERSCORE_NORMALIZER  # noqa: PLW0603
    if _VCS_UNDERSCORE_NORMALIZER is None:
        from sase.workspace_provider import get_workflow_names

        names = get_workflow_names()
        if not names:
            return prompt
        alts = "|".join(re.escape(n) for n in sorted(names))
        _VCS_UNDERSCORE_NORMALIZER = re.compile(
            rf"((?:^|(?<=\s)|(?<=[(\"']))#(?:{alts}))_",
            re.MULTILINE,
        )
    return _VCS_UNDERSCORE_NORMALIZER.sub(r"\1:", prompt)


def _get_vcs_tag_pattern() -> re.Pattern[str]:
    """Lazily initialize and return the VCS tag pattern."""
    global _VCS_TAG_PATTERN  # noqa: PLW0603
    if _VCS_TAG_PATTERN is None:
        from sase.workspace_provider import get_vcs_tag_pattern

        _VCS_TAG_PATTERN = get_vcs_tag_pattern()
    return _VCS_TAG_PATTERN


_DIRECTIVE_PREFIX_RE = re.compile(r"(%\S+[\s]+)+")


def extract_vcs_workflow_tag(prompt: str) -> str | None:
    """Extract a leading VCS workflow tag from a prompt string.

    Skips leading ``%directive`` tokens before checking for a VCS tag.
    Handles directives on the same line as the VCS tag (e.g. from
    Telegram-originated prompts like ``%n:a #gh_sase Fix the bug``).
    Returns the matched tag (e.g., ``"#gh:sase "``) or ``None``.
    """
    m = _DIRECTIVE_PREFIX_RE.match(prompt)
    stripped = prompt[m.end() :] if m else prompt

    match = _get_vcs_tag_pattern().match(stripped)
    if match:
        return match.group(0)
    return None


def strip_vcs_workflow_tag(prompt: str) -> str:
    """Strip a leading VCS workflow tag from a prompt string.

    Removes prefixes like ``#gh:sase``, ``#git(repo)``, ``#hg!!:cl``, etc.
    so the prompt can be re-wrapped with a different VCS workflow.
    """
    return _get_vcs_tag_pattern().sub("", prompt)


_VCS_REPLACE_PATTERN: re.Pattern[str] | None = None


def _get_vcs_replace_pattern() -> re.Pattern[str]:
    """Build a regex matching VCS workflow tags at the start of any line.

    Unlike :func:`_get_vcs_tag_pattern` (which is ``^``-anchored and matches
    only at the very start of the string), this pattern uses ``re.MULTILINE``
    so ``^`` matches at every line start.  Leading ``%directive`` tokens are
    captured in group 1 to be preserved during replacement.
    """
    global _VCS_REPLACE_PATTERN  # noqa: PLW0603
    if _VCS_REPLACE_PATTERN is None:
        from sase.workspace_provider import get_workflow_names

        names = "|".join(re.escape(n) for n in sorted(get_workflow_names()))
        _VCS_REPLACE_PATTERN = re.compile(
            rf"^((?:%\S+[\s]+)*)#(?:{names})(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s",
            re.MULTILINE,
        )
    return _VCS_REPLACE_PATTERN


def replace_vcs_workflow_tags(prompt: str, new_vcs_prefix: str) -> str:
    """Replace all VCS workflow tags in *prompt* with *new_vcs_prefix*.

    Handles multi-prompt segments (``---`` separated), directives before
    VCS tags, and VCS tags that appear at the start of any line.

    If no VCS tags are found, prepends *new_vcs_prefix* to the prompt.
    """
    pattern = _get_vcs_replace_pattern()
    result, count = pattern.subn(lambda m: f"{m.group(1)}{new_vcs_prefix} ", prompt)
    if count == 0:
        return f"{new_vcs_prefix} {prompt}"
    return result


def replace_ref_in_vcs_tag(tag: str, new_ref: str) -> str:
    """Replace the ref portion of a VCS workflow tag with *new_ref*.

    Strips HITL suffixes (``!!`` / ``??``) since this is used for resume
    scenarios where HITL overrides should not carry over.

    Handles colon format (``#gh:sase `` -> ``#gh:new_ref ``),
    parenthesized format (``#git(repo) `` -> ``#git(new_ref) ``),
    and underscore format (``#gh_sase `` -> ``#gh:new_ref ``).

    Args:
        tag: The VCS tag string as returned by :func:`extract_vcs_workflow_tag`.
        new_ref: The new ref to use (e.g. a branch name).

    Returns:
        The tag with the ref replaced and HITL suffixes stripped.
    """
    stripped = tag.rstrip()
    if not stripped.startswith("#"):
        return tag

    body = stripped[1:]  # strip leading #

    # Strip HITL suffixes (!! or ??)
    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break

    # Parenthesized ref: #git(repo) -> #git(new_ref)
    if "(" in body:
        paren_start = body.index("(")
        return f"#{body[:paren_start]}({new_ref}) "

    # Colon ref: #gh:sase -> #gh:new_ref
    if ":" in body:
        prefix = body.split(":", 1)[0]
        return f"#{prefix}:{new_ref} "

    # Underscore ref: #gh_sase -> #gh:new_ref
    if "_" in body:
        prefix = body.split("_", 1)[0]
        return f"#{prefix}:{new_ref} "

    # No ref (bare #gh) - append with colon
    return f"#{body}:{new_ref} "


def extract_project_from_vcs_tag(tag: str) -> str | None:
    """Extract the project/ref name from a VCS workflow tag.

    Handles formats like ``#gh:sase ``, ``#gh!!:sase ``, ``#git(repo) ``.
    Returns the ref portion (e.g. ``"sase"``, ``"repo"``) or ``None`` if
    no ref is present.

    Args:
        tag: The VCS tag string as returned by :func:`extract_vcs_workflow_tag`.
    """
    tag = tag.strip()
    if not tag.startswith("#"):
        return None

    body = tag[1:]  # strip leading #

    # Strip optional !! or ?? HITL suffix from the workflow-type portion
    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break

    # Parenthesized ref: #git(repo) -> repo
    if "(" in body:
        start = body.index("(")
        end = body.find(")", start)
        if end != -1:
            return body[start + 1 : end] or None
        return None

    # Colon ref: #gh:sase -> sase
    if ":" in body:
        ref = body.split(":", 1)[1]
        return ref or None

    # No ref (e.g. #gh+ or bare #gh)
    return None


__all__ = [
    "DOUBLE_COLON_SHORTHAND_PATTERN",
    "SHORTHAND_PATTERN",
    "XPROMPT_REFERENCE_ARGUMENT_FRAGMENT",
    "XPROMPT_REFERENCE_HITL_SUFFIX_FRAGMENT",
    "XPROMPT_REFERENCE_LEADING_CONTEXT",
    "XPROMPT_REFERENCE_MARKER_FRAGMENT",
    "XPROMPT_REFERENCE_NAME_FRAGMENT",
    "XPROMPT_REFERENCE_PATTERN",
    "XPromptReference",
    "XPromptReferenceArgKind",
    "XPromptReferenceMarker",
    "_format_as_text_block",
    "_parse_named_arg",
    "_preprocess_paren_shorthand",
    "_process_text_block",
    "escape_for_xprompt",
    "extract_project_from_vcs_tag",
    "extract_vcs_workflow_tag",
    "find_double_colon_text_end",
    "find_matching_paren_for_args",
    "find_shorthand_text_end",
    "iter_xprompt_references",
    "normalize_vcs_underscore_refs",
    "parse_args",
    "parse_workflow_reference",
    "preprocess_shorthand_syntax",
    "replace_ref_in_vcs_tag",
    "replace_vcs_workflow_tags",
    "strip_hitl_suffix",
    "strip_vcs_workflow_tag",
    "xprompt_reference_from_match",
]

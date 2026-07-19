"""Cheap prompt directive scanning and side-effect-free stripping."""

import re

from ._directive_types import (
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
)
from ._disabled_regions import protect_disabled_regions
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_paren_for_args


def strip_known_directives(prompt: str) -> str:
    """Remove known ``%id`` directive spans from *prompt* without side effects.

    Side-effect-free counterpart to ``extract_prompt_directives``: it strips
    the same known/directive-migration spans (colon, paren, backtick, and plus
    argument forms, plus short aliases) but never allocates auto-names, resolves
    ``%wait`` arguments, or raises on duplicate or bare directives. Unknown
    Unknown ``%directive`` tokens and directives inside fenced code blocks are left
    untouched.
    """
    if "%" not in prompt:
        return prompt

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    regions_to_remove: list[tuple[int, int]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in _KNOWN_DIRECTIVES and name not in _DEPRECATED_DIRECTIVES:
            continue
        match_end = match.end()
        if match.group(2) is not None:
            paren_end = find_matching_paren_for_args(protected, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        regions_to_remove.append((match.start(), match_end))

    cleaned = protected
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]

    return unprotect_fenced_blocks(cleaned, fenced_blocks)


def has_deferred_start_directive(prompt: str) -> bool:
    """Quick check whether a prompt defers launch."""
    if _has_wait_directive(prompt) or _has_t_time_xprompt_reference(prompt):
        return True
    if "#fork" not in prompt:
        return False
    from sase.agent.names import has_fork_reference

    return has_fork_reference(prompt)


def has_model_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%model`` or ``%m`` directives."""
    return _has_protected_directive_match(
        prompt,
        r"(?:^|\s)%(?:model|m)(?:[:+(]|\s|$)",
    )


def _has_wait_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains ``%wait`` or ``%w`` directives."""
    return _has_protected_directive_match(
        prompt,
        r"(?:^|\s)%(?:wait|w)(?:[:+(]|\s|$)",
    )


def _has_protected_directive_match(prompt: str, pattern: str) -> bool:
    """Run a cheap directive predicate after extractor-equivalent protection."""
    return _has_protected_pattern_match(prompt, pattern, required_substring="%")


def _has_t_time_xprompt_reference(prompt: str) -> bool:
    """Quick check whether a prompt contains an explicit ``#t`` time wait."""
    return _has_protected_pattern_match(
        prompt,
        r"(?:^|(?<=\s)|(?<=[(\[{\"']))#t(?=[:(])",
        required_substring="#t",
    )


def _has_protected_pattern_match(
    prompt: str, pattern: str, *, required_substring: str
) -> bool:
    """Run a cheap predicate after fenced-block and disabled-region protection."""
    if required_substring not in prompt:
        return False

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    return bool(re.search(pattern, protected, re.MULTILINE))

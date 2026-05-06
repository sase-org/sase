"""Shared prompt helpers for retrying agents."""

from __future__ import annotations

import re


def rewrite_retry_prompt_name(raw_prompt: str, retry_name: str) -> str:
    """Replace or prepend the top-level prompt name directive for retry."""
    from sase.xprompt._directive_types import (
        _DIRECTIVE_ALIASES,
        _DIRECTIVE_PATTERN,
    )
    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(raw_prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "name":
            continue

        match_end = match.end()
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                match_end = paren_end + 1

        rewritten = (
            f"{protected[: match.start()]}%name:{retry_name}{protected[match_end:]}"
        )
        rewritten = unprotect_disabled_regions(rewritten, disabled)
        return unprotect_fenced_blocks(rewritten, fenced)

    protected = f"%name:{retry_name}\n{protected}"
    protected = unprotect_disabled_regions(protected, disabled)
    return unprotect_fenced_blocks(protected, fenced)

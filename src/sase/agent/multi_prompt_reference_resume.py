"""Resume-reference parsing and rewriting for multi-prompt launches."""

import re

_BARE_RESUME_RE = re.compile(r"#fork(?![A-Za-z0-9_])")
_RESUME_REF_RE = re.compile(
    r"#(?P<kind>fork|resume)(?![A-Za-z0-9_])"
    r"(?:"
    r":(?P<colon>`[^`]*`|[^\s)]+)"
    r"|"
    r"(?P<open_paren>\()"
    r")"
)
_XPROMPT_REF_RE = re.compile(r"#([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)")


def has_bare_resume_reference(prompt: str) -> bool:
    """Return True when *prompt* contains a top-level bare ``#fork``."""
    if "#fork" not in prompt:
        return False

    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    return any(
        _is_bare_resume_match(protected, match)
        for match in _BARE_RESUME_RE.finditer(protected)
    )


def rewrite_bare_resume_references(prompt: str, agent_name: str) -> str:
    """Rewrite top-level bare ``#fork`` references to *agent_name*."""
    if "#fork" not in prompt:
        return prompt

    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in _BARE_RESUME_RE.finditer(protected):
        if _is_bare_resume_match(protected, match):
            replacements.append((match.start(), match.end(), f"#fork:{agent_name}"))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _is_bare_resume_match(text: str, match: re.Match[str]) -> bool:
    if match.end() >= len(text):
        return True
    return text[match.end()] not in ":("


def has_non_resume_xprompt_reference(prompt: str) -> bool:
    if "#" not in prompt:
        return False

    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    return any(
        match.group(1) not in {"fork", "resume"}
        for match in _XPROMPT_REF_RE.finditer(protected)
    )

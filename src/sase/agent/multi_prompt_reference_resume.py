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
_MACRO_REF_RE = re.compile(r"#([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)")


def has_bare_resume_reference(prompt: str) -> bool:
    """Return True when ``#fork`` needs the previous prompt's agent name."""
    if "#fork" not in prompt:
        return False

    from sase.macro._disabled_regions import protect_disabled_regions
    from sase.macro._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    matches = list(_BARE_RESUME_RE.finditer(protected))
    if any(_is_bare_resume_match(protected, match) for match in matches):
        return True

    from sase.macro._parsing import find_matching_paren_for_args, parse_args

    for match in matches:
        if match.end() >= len(protected) or protected[match.end()] != "(":
            continue
        paren_end = find_matching_paren_for_args(protected, match.end())
        if paren_end is None:
            continue
        positional, named = parse_args(protected[match.end() + 1 : paren_end])
        if not positional and "target" in named and not named.get("name"):
            return True
    return False


def rewrite_bare_resume_references(prompt: str, agent_name: str) -> str:
    """Bind bare and target-only top-level ``#fork`` refs to *agent_name*."""
    if "#fork" not in prompt:
        return prompt

    from sase.macro._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.macro._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.macro._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in _BARE_RESUME_RE.finditer(protected):
        if _is_bare_resume_match(protected, match):
            replacements.append((match.start(), match.end(), f"#fork:{agent_name}"))
            continue
        if match.end() >= len(protected) or protected[match.end()] != "(":
            continue
        paren_end = find_matching_paren_for_args(protected, match.end())
        if paren_end is None:
            continue
        inner = protected[match.end() + 1 : paren_end]
        try:
            positional, named = parse_args(
                inner,
                reject_duplicate_named_args=True,
            )
        except ValueError:
            # Leave the malformed form intact for the launch scan to report.
            continue
        if positional or "target" not in named or named.get("name"):
            continue
        rendered = [agent_name]
        rendered.extend(f"{key}={value}" for key, value in named.items())
        replacements.append(
            (match.start(), paren_end + 1, f"#fork({','.join(rendered)})")
        )

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _is_bare_resume_match(text: str, match: re.Match[str]) -> bool:
    if match.end() >= len(text):
        return True
    return text[match.end()] not in ":("


def has_non_resume_macro_reference(prompt: str) -> bool:
    if "#" not in prompt:
        return False

    from sase.macro._disabled_regions import protect_disabled_regions
    from sase.macro._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    return any(
        match.group(1) not in {"fork", "resume"}
        for match in _MACRO_REF_RE.finditer(protected)
    )

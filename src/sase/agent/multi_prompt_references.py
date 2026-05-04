"""Name planning and reference rewrites for multi-prompt launches."""

import json
import os
import re
import time

_PLANNED_AGENT_NAME_ENV = "SASE_AGENT_PLANNED_NAME"


def wait_for_agent_naming(artifacts_dir: str, timeout: float = 30) -> str | None:
    """Poll ``agent_meta.json`` for a ``name`` field.

    Returns the agent name when found, or ``None`` on timeout.
    """
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with open(meta_path) as f:
                data = json.load(f)
            if data.get("name"):
                return data["name"]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return None


def extract_static_name_directive(prompt: str) -> str | None:
    """Return an explicit top-level ``%name`` value that is safe to reuse."""
    if "%" not in prompt:
        return None

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "name":
            continue

        value = ""
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                inner = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(inner)
                value = positional_args[0] if positional_args else ""
        elif match.group(3) is not None:
            colon_arg = match.group(3)
            value = (
                colon_arg[1:-1]
                if colon_arg.startswith("`") and colon_arg.endswith("`")
                else colon_arg
            )

        if not value or "#" in value:
            return None
        return value
    return None


def has_bare_wait_directive(prompt: str) -> bool:
    """Return True when *prompt* contains a top-level bare ``%wait``."""
    if "%" not in prompt:
        return False

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        return True
    return False


def rewrite_bare_wait_directives(prompt: str, agent_name: str) -> str:
    """Rewrite top-level bare ``%wait``/``%w`` directives to *agent_name*."""
    if "%" not in prompt:
        return prompt

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
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
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
            end = paren_end + 1 if paren_end is not None else match.end()
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        else:
            end = match.end()
        replacements.append((match.start(), end, f"%{raw_name}:{agent_name}"))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


_BARE_RESUME_RE = re.compile(r"#resume(?![A-Za-z0-9_])")


def has_bare_resume_reference(prompt: str) -> bool:
    """Return True when *prompt* contains a top-level bare ``#resume``."""
    if "#resume" not in prompt:
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
    """Rewrite top-level bare ``#resume`` references to *agent_name*."""
    if "#resume" not in prompt:
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
            replacements.append((match.start(), match.end(), f"#resume:{agent_name}"))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _is_bare_resume_match(text: str, match: re.Match[str]) -> bool:
    if match.end() >= len(text):
        return True
    return text[match.end()] not in ":("


class PlannedNameAllocator:
    """Allocate parent-side names for multi-prompt wait rewrites."""

    def __init__(self) -> None:
        self._auto_reserved: set[str] | None = None

    def planned_name_for_prompt(self, prompt: str) -> tuple[str | None, str | None]:
        """Return ``(name, env_value)`` for a prompt, if safely knowable."""
        explicit_name = extract_static_name_directive(prompt)
        if explicit_name is not None:
            return explicit_name, None

        if "#" in prompt:
            return None, None

        from sase.agent.names import allocate_auto_names

        if self._auto_reserved is None:
            from sase.agent.names import get_active_agent_names

            self._auto_reserved = get_active_agent_names()
        name = allocate_auto_names(1, reserved=self._auto_reserved)[0]
        return name, name

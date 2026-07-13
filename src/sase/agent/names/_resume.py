"""Derived agent-name parsing and allocation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import re
import threading

from sase.core.paths import sase_home
from sase.xprompt._disabled_regions import protect_disabled_regions
from sase.xprompt._fenced_blocks import protect_fenced_blocks
from sase.xprompt._parsing import (
    find_matching_paren_for_args,
    parse_args,
)

_RESUME_REF_RE = re.compile(
    r"#(?:fork|resume)(?![A-Za-z0-9_])"
    r"(?:"
    r":(?P<colon>`[^`]*`|[^\s,)]+)"
    r"|"
    r"(?P<open_paren>\()"
    r")"
)

_FORK_REF_RE = re.compile(
    r"#fork(?![A-Za-z0-9_])"
    r"(?:"
    r":(?P<colon>`[^`]*`|[^\s,)]+)"
    r"|"
    r"(?P<open_paren>\()"
    r")"
)

_PROCESS_NAME_LOCK = threading.RLock()
_LOCK_STATE = threading.local()


@contextmanager
def agent_name_allocation_lock() -> Iterator[None]:
    """Serialize scan-and-claim flows for derived agent names."""
    with _PROCESS_NAME_LOCK:
        depth = getattr(_LOCK_STATE, "depth", 0)
        if depth > 0:
            _LOCK_STATE.depth = depth + 1
            try:
                yield
            finally:
                _LOCK_STATE.depth = depth
            return

        lock_path = sase_home() / "agent_name_allocation.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            _LOCK_STATE.depth = 1
            try:
                yield
            finally:
                _LOCK_STATE.depth = 0
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def first_resume_agent_name(prompt: str | None) -> str | None:
    """Return the first top-level ``#fork`` or legacy ``#resume`` target.

    ``#fork_by_chat`` and legacy ``#resume_by_chat`` are intentionally ignored
    because their arguments are chat paths, not agent names. Fenced code blocks
    and disabled xprompt regions are protected before lexical matching.
    """
    for arg in _iter_reference_args(prompt, _RESUME_REF_RE, "#fork", "#resume"):
        from sase.agent.names._templates import resolve_agent_name_template_reference

        return resolve_agent_name_template_reference(arg)
    return None


def first_fork_agent_name(prompt: str | None) -> str | None:
    """Return the first top-level ``#fork:<name>`` target, if any.

    Unlike :func:`first_resume_agent_name`, legacy ``#resume`` references are
    not matched: this is used to derive an implicit ``%wait`` dependency, and
    only ``#fork`` should imply a wait. ``#fork_by_chat`` (chat-path argument)
    and bare ``#fork`` (target resolved dynamically by the fork workflow) carry
    no explicit agent name and are intentionally excluded. Fenced code blocks
    and disabled xprompt regions are protected before lexical matching.
    """
    for arg in _iter_reference_args(prompt, _FORK_REF_RE, "#fork"):
        from sase.agent.names._templates import resolve_agent_name_template_reference

        return resolve_agent_name_template_reference(arg)
    return None


def has_fork_reference(prompt: str | None) -> bool:
    """Return True when *prompt* contains a top-level explicit ``#fork`` target.

    This is detection-only: unlike :func:`first_fork_agent_name`, it does not
    resolve agent-name templates, touch active-agent state, or raise when a
    template reference such as ``#fork:build-@`` has no concrete match yet.
    """
    return next(_iter_reference_args(prompt, _FORK_REF_RE, "#fork"), None) is not None


def allocate_resume_name(
    resume_name: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Return the first available rendering of ``<resume_name>.f@``."""
    from sase.agent.names._templates import allocate_agent_name_template

    return allocate_agent_name_template(
        resume_agent_name_template(resume_name),
        reserved=reserved,
    )


def allocate_resume_names(resume_name: str, count: int) -> list[str]:
    """Allocate *count* resume-derived names from one registry snapshot."""
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    from sase.agent.names._registry import get_reserved_agent_names
    from sase.agent.names._templates import (
        AgentNameNamespaceReservationIndex,
        allocate_agent_name_template,
    )

    reserved = get_reserved_agent_names()
    index = AgentNameNamespaceReservationIndex.from_names(reserved)
    template = resume_agent_name_template(resume_name)
    return [
        allocate_agent_name_template(template, reserved=reserved, index=index)
        for _ in range(count)
    ]


def active_resume_reserved_names(resume_name: str) -> set[str]:
    """Return the registry snapshot used for resume-derived allocation."""
    del resume_name
    from sase.agent.names._registry import get_reserved_agent_names

    return get_reserved_agent_names()


def resume_agent_name_template(base: str) -> str:
    """Return the template used for fork/resume-derived agent names."""
    return f"{base}.f@"


def single_wait_agent_name(prompt: str | None) -> str | None:
    """Return the sole parsed ``%wait`` agent dependency, if unambiguous."""
    if not prompt or "%" not in prompt:
        return None
    if _has_non_explicit_wait_directive(prompt):
        return None

    try:
        from sase.xprompt.directives import extract_prompt_directives
        from sase.xprompt._exceptions import DirectiveError

        _, directives = extract_prompt_directives(prompt)
    except DirectiveError:
        return None

    return directives.wait[0] if len(directives.wait) == 1 else None


def _has_non_explicit_wait_directive(prompt: str) -> bool:
    """Return True for bare/plus/empty ``%wait`` directives."""
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
            return True
        if match.group(3) is not None:
            continue
        return True
    return False


def allocate_wait_name(
    wait_name: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Return the first available rendering of ``<wait_name>.w@``."""
    from sase.agent.names._templates import allocate_agent_name_template

    return allocate_agent_name_template(
        wait_agent_name_template(wait_name),
        reserved=reserved,
    )


def allocate_wait_names(wait_name: str, count: int) -> list[str]:
    """Allocate *count* wait-derived names from one registry snapshot."""
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    from sase.agent.names._registry import get_reserved_agent_names
    from sase.agent.names._templates import (
        AgentNameNamespaceReservationIndex,
        allocate_agent_name_template,
    )

    reserved = get_reserved_agent_names()
    index = AgentNameNamespaceReservationIndex.from_names(reserved)
    template = wait_agent_name_template(wait_name)
    return [
        allocate_agent_name_template(template, reserved=reserved, index=index)
        for _ in range(count)
    ]


def active_wait_reserved_names(wait_name: str) -> set[str]:
    """Return the registry snapshot used for wait-derived allocation."""
    del wait_name
    from sase.agent.names._registry import get_reserved_agent_names

    return get_reserved_agent_names()


def wait_agent_name_template(base: str) -> str:
    """Return the template used for wait-derived agent names."""
    return f"{base}.w@"


def _iter_reference_args(
    prompt: str | None,
    pattern: re.Pattern[str],
    *guard_substrings: str,
) -> Iterator[str]:
    if not prompt:
        return
    if guard_substrings and not any(guard in prompt for guard in guard_substrings):
        return

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in pattern.finditer(protected):
        arg = _resume_reference_argument(protected, match)
        if arg:
            yield arg


def _resume_reference_argument(text: str, match: re.Match[str]) -> str | None:
    colon = match.group("colon")
    if colon is not None:
        raw = colon
        if raw.startswith("`") and raw.endswith("`"):
            return raw[1:-1] or None
        return raw or None
    if match.group("open_paren") is not None:
        paren_start = match.end("open_paren") - 1
        paren_end = find_matching_paren_for_args(text, paren_start)
        if paren_end is None:
            return None
        inner = text[paren_start + 1 : paren_end]
        positional, _ = parse_args(inner)
        return positional[0] if positional else None
    return None

"""Derived agent-name parsing and allocation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path
import re
import threading

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

        lock_path = Path.home() / ".sase" / "agent_name_allocation.lock"
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
    if not prompt or ("#fork" not in prompt and "#resume" not in prompt):
        return None

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in _RESUME_REF_RE.finditer(protected):
        arg = _resume_reference_argument(protected, match)
        if arg:
            return arg
    return None


def allocate_resume_name(
    resume_name: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Return the first available ``<resume_name>.f<N>`` name.

    Existing fork names and legacy ``.r<N>`` descendants both reserve the
    numeric slot, so ``foo.r1.claude`` causes the next allocation for ``foo``
    to skip ``foo.f1``.
    """
    pool = _active_resume_reserved_names(resume_name) if reserved is None else reserved
    n = 1
    while True:
        candidate = f"{resume_name}.f{n}"
        if candidate not in pool:
            pool.add(candidate)
            return candidate
        n += 1


def allocate_resume_names(resume_name: str, count: int) -> list[str]:
    """Allocate *count* resume-derived names from one active-name snapshot."""
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    reserved = _active_resume_reserved_names(resume_name)
    return [allocate_resume_name(resume_name, reserved=reserved) for _ in range(count)]


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
    """Return the first available ``<wait_name>.w<N>`` name."""
    pool = active_wait_reserved_names(wait_name) if reserved is None else reserved
    n = 1
    while True:
        candidate = f"{wait_name}.w{n}"
        if candidate not in pool:
            pool.add(candidate)
            return candidate
        n += 1


def allocate_wait_names(wait_name: str, count: int) -> list[str]:
    """Allocate *count* wait-derived names from one active-name snapshot."""
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    reserved = active_wait_reserved_names(wait_name)
    return [allocate_wait_name(wait_name, reserved=reserved) for _ in range(count)]


def active_wait_reserved_names(wait_name: str) -> set[str]:
    """Return active names that reserve ``<wait_name>.w<N>`` slots."""
    from sase.agent.names._auto import get_active_agent_names

    active = get_active_agent_names()
    pattern = re.compile(rf"^{re.escape(wait_name)}\.w(\d+)(?:\.|$)")
    reserved: set[str] = set()
    for name in active:
        match = pattern.match(name)
        if match is None:
            continue
        reserved.add(f"{wait_name}.w{match.group(1)}")
    return reserved


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


def _active_resume_reserved_names(resume_name: str) -> set[str]:
    from sase.agent.names._auto import get_active_agent_names

    active = get_active_agent_names()
    pattern = re.compile(rf"^{re.escape(resume_name)}\.[fr](\d+)(?:\.|$)")
    reserved: set[str] = set()
    for name in active:
        match = pattern.match(name)
        if match is None:
            continue
        reserved.add(f"{resume_name}.f{match.group(1)}")
    return reserved

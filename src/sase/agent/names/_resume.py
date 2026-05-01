"""Resume-derived agent-name parsing and allocation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path
import re

from sase.xprompt._disabled_regions import protect_disabled_regions
from sase.xprompt._fenced_blocks import protect_fenced_blocks
from sase.xprompt._parsing import (
    find_matching_paren_for_args,
    parse_args,
)

_RESUME_REF_RE = re.compile(
    r"#resume(?![A-Za-z0-9_])"
    r"(?:"
    r":(?P<colon>`[^`]*`|[^\s,)]+)"
    r"|"
    r"(?P<open_paren>\()"
    r")"
)


@contextmanager
def agent_name_allocation_lock() -> Iterator[None]:
    """Serialize scan-and-claim flows for derived agent names."""
    lock_path = Path.home() / ".sase" / "agent_name_allocation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def first_resume_agent_name(prompt: str | None) -> str | None:
    """Return the first top-level ``#resume`` target in *prompt*.

    ``#resume_by_chat`` is intentionally ignored because its argument is a
    chat path, not an agent name. Fenced code blocks and disabled xprompt
    regions are protected before lexical matching.
    """
    if not prompt or "#resume" not in prompt:
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
    """Return the first available ``<resume_name>.r<N>`` name.

    Existing exact resume names and suffixed descendants both reserve the
    numeric slot, so ``foo.r1.claude`` causes the next allocation for ``foo``
    to skip ``foo.r1``.
    """
    pool = _active_resume_reserved_names(resume_name) if reserved is None else reserved
    n = 1
    while True:
        candidate = f"{resume_name}.r{n}"
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
    pattern = re.compile(rf"^{re.escape(resume_name)}\.r(\d+)(?:\.|$)")
    reserved: set[str] = set()
    for name in active:
        match = pattern.match(name)
        if match is None:
            continue
        reserved.add(f"{resume_name}.r{match.group(1)}")
    return reserved

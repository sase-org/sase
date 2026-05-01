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
_RESUME_ROLE_SEGMENTS = {"code", "plan"}
_RESUME_GENERATION_SEGMENT_RE = re.compile(r"^r(\d+)$")


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
    """Return the first available normalized ``<resume_name>.r<N>`` name.

    Existing exact resume names and suffixed descendants both reserve the
    numeric slot, so ``foo.r1.claude`` causes the next allocation for ``foo``
    to skip ``foo.r1``.
    """
    base_name, generation_floor = _normalize_resume_name_for_allocation(resume_name)
    pool = _active_resume_reserved_names(resume_name) if reserved is None else reserved
    n = generation_floor
    while True:
        candidate = f"{base_name}.r{n}"
        if candidate not in pool:
            pool.add(candidate)
            return candidate
        n += 1


def allocate_resume_names(resume_name: str, count: int) -> list[str]:
    """Allocate *count* resume-derived names from one active-name snapshot."""
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    base_name, generation_floor = _normalize_resume_name_for_allocation(resume_name)
    reserved = _active_resume_reserved_names(resume_name)
    names: list[str] = []
    for _ in range(count):
        n = generation_floor
        while True:
            candidate = f"{base_name}.r{n}"
            if candidate not in reserved:
                reserved.add(candidate)
                names.append(candidate)
                break
            n += 1
    return names


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


def _normalize_resume_name_for_allocation(resume_name: str) -> tuple[str, int]:
    stripped_segments = [
        segment
        for segment in resume_name.split(".")
        if segment not in _RESUME_ROLE_SEGMENTS
    ]
    if not stripped_segments:
        return resume_name, 1

    generation_floor = _resume_generation_floor(resume_name)
    first_generation_index = _first_resume_generation_segment_index(stripped_segments)
    if first_generation_index is None:
        return ".".join(stripped_segments), generation_floor
    if first_generation_index == 0:
        return ".".join(stripped_segments), 1
    return ".".join(stripped_segments[:first_generation_index]), generation_floor


def _resume_generation_floor(resume_name: str) -> int:
    stripped_segments = [
        segment
        for segment in resume_name.split(".")
        if segment not in _RESUME_ROLE_SEGMENTS
    ]
    return _resume_generation_floor_from_segments(stripped_segments)


def _resume_generation_floor_from_segments(segments: list[str]) -> int:
    generations = [
        int(match.group(1))
        for index, segment in enumerate(segments)
        if index > 0
        if (match := _RESUME_GENERATION_SEGMENT_RE.fullmatch(segment)) is not None
    ]
    if not generations:
        return 1
    return max(generations) + 1


def _first_resume_generation_segment_index(segments: list[str]) -> int | None:
    for index, segment in enumerate(segments):
        if index > 0 and _RESUME_GENERATION_SEGMENT_RE.fullmatch(segment):
            return index
    return None


def _active_resume_reserved_names(resume_name: str) -> set[str]:
    from sase.agent.names._auto import get_active_agent_names

    base_name, _ = _normalize_resume_name_for_allocation(resume_name)
    active = get_active_agent_names()
    pattern = re.compile(rf"^{re.escape(base_name)}\.r(\d+)(?:\.|$)")
    reserved: set[str] = set()
    for name in active:
        match = pattern.match(name)
        if match is None:
            continue
        reserved.add(f"{base_name}.r{match.group(1)}")
    return reserved

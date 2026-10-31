"""Derived agent-name parsing and allocation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import re
import threading
import time

from sase.core.paths import sase_home
from sase.macro._disabled_regions import protect_disabled_regions
from sase.macro._fenced_blocks import protect_fenced_blocks
from sase.macro._parsing import (
    find_matching_paren_for_args,
    parse_args,
)

_RESUME_REF_RE = re.compile(
    r"#(?P<kind>fork|resume)(?![A-Za-z0-9_])"
    r"(?:"
    r":(?P<colon>`[^`]*`|[^\s)]+)"
    r"|"
    r"(?P<open_paren>\()"
    r")"
)


@dataclass(frozen=True, slots=True)
class ForkReference:
    """One explicit fork parent and its requested wait target."""

    name: str
    target: str | None = None
    target_explicit: bool = False


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
            from sase.agent.launch_timing import active_launch_timing_recorder

            timer = active_launch_timing_recorder()
            wait_start = time.perf_counter()
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            wait_ms = (time.perf_counter() - wait_start) * 1000.0
            _LOCK_STATE.depth = 1
            try:
                if timer is None:
                    yield
                else:
                    with timer.stage("registry_lock_hold", lock_wait_ms=wait_ms):
                        yield
            finally:
                _LOCK_STATE.depth = 0
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def first_resume_agent_name(prompt: str | None) -> str | None:
    """Return the first parent for callers that explicitly want first-only behavior."""
    for kind, args in _iter_reference_arg_groups(prompt):
        if args:
            if kind == "fork" and _is_tribe_reference(args[0]):
                return args[0]
            return _resolve_fork_agent_reference(args[0])
    return None


def sole_resume_agent_name(prompt: str | None) -> str | None:
    """Return the sole parent eligible for resume-derived naming.

    ``#fork_by_chat`` and legacy ``#resume_by_chat`` are intentionally ignored
    because their arguments are chat paths, not agent names. Fenced code blocks
    and disabled macro regions are protected before lexical matching. A fork
    with two or more parents deliberately returns ``None`` so merged children
    use neutral auto-naming. Legacy ``#resume`` remains single-parent.
    """
    groups = list(_iter_reference_arg_groups(prompt))
    if not groups:
        return None

    first_kind, first_args = groups[0]
    if first_kind == "resume":
        return _resolve_fork_agent_reference(first_args[0]) if first_args else None

    parents = _resolved_fork_agent_names(groups)
    if len(parents) == 1:
        if _is_tribe_reference(parents[0]):
            return None
        return parents[0]
    return None


def fork_agent_names(prompt: str | None) -> list[str]:
    """Return all explicit fork parents in stable, de-duplicated order."""
    names: list[str] = []
    for reference in fork_references(prompt):
        if reference.name not in names:
            names.append(reference.name)
    return names


def fork_references(prompt: str | None) -> list[ForkReference]:
    """Return structured fork parents, resolving agent-name templates."""
    if not prompt or "#fork" not in prompt:
        return []

    references: list[ForkReference] = []
    for match in _iter_protected_reference_matches(prompt):
        if match.group("kind") != "fork":
            continue
        for reference in _resume_reference_arguments(prompt, match):
            if not reference.name:
                continue
            name = (
                reference.name
                if _is_tribe_reference(reference.name)
                else _resolve_fork_agent_reference(reference.name)
            )
            references.append(
                ForkReference(
                    name=name,
                    target=reference.target,
                    target_explicit=reference.target_explicit,
                )
            )
    return references


def first_fork_agent_name(prompt: str | None) -> str | None:
    """Return the first top-level ``#fork:<name>`` target, if any.

    Unlike :func:`first_resume_agent_name`, legacy ``#resume`` references are
    not matched: this is used to derive an implicit ``%wait`` dependency, and
    only ``#fork`` should imply a wait. ``#fork_by_chat`` (chat-path argument)
    and bare ``#fork`` (target resolved dynamically by the fork workflow) carry
    no explicit agent name and are intentionally excluded. Fenced code blocks
    and disabled macro regions are protected before lexical matching.
    """
    parents = fork_agent_names(prompt)
    return parents[0] if parents else None


def has_fork_reference(prompt: str | None) -> bool:
    """Return True when *prompt* contains a top-level explicit ``#fork`` target.

    This is detection-only: unlike :func:`first_fork_agent_name`, it does not
    resolve agent-name templates, touch active-agent state, or raise when a
    template reference such as ``#fork:build-@`` has no concrete match yet.
    """
    for match in _iter_protected_reference_matches(prompt):
        text = match.string or ""
        if match.group("kind") != "fork":
            continue
        if match.group("colon") is not None:
            if match.group("colon"):
                return True
            continue
        if match.group("open_paren") is None:
            continue
        paren_start = match.end("open_paren") - 1
        paren_end = find_matching_paren_for_args(text, paren_start)
        if paren_end is not None and text[paren_start + 1 : paren_end].strip():
            return True
    return False


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
    """Return the template used for fork/resume-derived agent names.

    An agent-session member such as ``foo--code`` contributes its agent-session name so the
    derived child is ``foo.f@`` rather than the unclassifiable ``foo--code.f@``.
    """
    from sase.agent.names._generation_guard import generated_child_name_base

    return f"{generated_child_name_base(base)}.f@"


def single_wait_agent_name(prompt: str | None) -> str | None:
    """Return the sole parsed ``%wait`` agent dependency, if unambiguous."""
    if not prompt or "%" not in prompt:
        return None
    if _has_non_explicit_wait_directive(prompt):
        return None

    try:
        from sase.macro.directives import extract_prompt_directives
        from sase.macro._exceptions import DirectiveError

        _, directives = extract_prompt_directives(prompt)
    except DirectiveError:
        return None

    return directives.wait[0] if len(directives.wait) == 1 else None


def _has_non_explicit_wait_directive(prompt: str) -> bool:
    """Return True for bare/plus/empty ``%wait`` directives."""
    from sase.macro._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.macro._disabled_regions import protect_disabled_regions
    from sase.macro._fenced_blocks import protect_fenced_blocks
    from sase.macro._parsing import find_matching_paren_for_args

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
    from sase.agent.names._generation_guard import generated_child_name_base

    return f"{generated_child_name_base(base)}.w@"


def _iter_reference_arg_groups(
    prompt: str | None,
) -> Iterator[tuple[str, list[str]]]:
    for match in _iter_protected_reference_matches(prompt):
        references = _resume_reference_arguments(prompt or "", match)
        names = [reference.name for reference in references if reference.name]
        if names:
            yield match.group("kind"), names


def _iter_protected_reference_matches(
    prompt: str | None,
) -> Iterator[re.Match[str]]:
    if not prompt or ("#fork" not in prompt and "#resume" not in prompt):
        return
    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)
    yield from _RESUME_REF_RE.finditer(protected)


def _resume_reference_arguments(
    text: str,
    match: re.Match[str],
) -> list[ForkReference]:
    # Matches are found in a protected copy with fenced/disabled regions
    # replaced by placeholders. Parenthesized argument offsets must be read
    # against that same copy, since its offsets no longer align with *text*.
    text = match.string or ""
    colon = match.group("colon")
    if colon is not None:
        if colon.startswith("`") and colon.endswith("`"):
            value = colon[1:-1]
            positional = [value] if value else []
            named: dict[str, str] = {}
        else:
            positional, named = parse_args(colon, preserve_empty_args=True)
        if match.group("kind") == "fork" and named:
            raise ValueError(
                "Named #fork inputs require parenthesized syntax; "
                "write #fork(name=parent, target=turn)."
            )
        return [ForkReference(name=value) for value in positional if value]
    if match.group("open_paren") is not None:
        paren_start = match.end("open_paren") - 1
        paren_end = find_matching_paren_for_args(text, paren_start)
        if paren_end is None:
            return []
        inner = text[paren_start + 1 : paren_end]
        try:
            positional, named = parse_args(
                inner,
                reject_duplicate_named_args=True,
                preserve_empty_args=True,
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid #{match.group('kind')} arguments: {exc}"
            ) from exc
        if match.group("kind") != "fork":
            return [ForkReference(name=value) for value in positional if value]

        unexpected = set(named) - {"name", "target"}
        if unexpected:
            unexpected_names = ", ".join(sorted(unexpected))
            raise ValueError(f"Unsupported named #fork input(s): {unexpected_names}")
        parsed_names = [value for value in positional if value]
        named_name = named.get("name")
        if named_name:
            parsed_names.append(named_name)
        target = named.get("target")
        if target is not None:
            from sase.core.wait_target_facade import parse_wait_target

            try:
                target = parse_wait_target(target)
            except (RuntimeError, ValueError) as exc:
                raise ValueError(f"Invalid #fork target={target!r}: {exc}") from exc
        return [
            ForkReference(
                name=value,
                target=target,
                target_explicit=target is not None,
            )
            for value in parsed_names
        ]
    return []


def _resolved_fork_agent_names(
    groups: list[tuple[str, list[str]]],
) -> list[str]:
    resolved: list[str] = []
    for kind, args in groups:
        if kind != "fork":
            continue
        for arg in args:
            name = (
                arg if _is_tribe_reference(arg) else _resolve_fork_agent_reference(arg)
            )
            if name not in resolved:
                resolved.append(name)
    return resolved


def _is_tribe_reference(name: str) -> bool:
    """Return whether *name* is a validated next-entity tribe target."""
    from sase.core.agent_tribe import parse_tribe_reference

    return parse_tribe_reference(name) is not None


def _resolve_fork_agent_reference(name: str) -> str:
    """Resolve templates while excluding the agent being launched."""
    from sase.agent.names._templates import (
        is_agent_name_template,
        require_latest_agent_name_template,
        resolve_agent_name_template_reference,
    )

    if not is_agent_name_template(name):
        return resolve_agent_name_template_reference(name)

    current_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not current_artifacts_dir:
        return resolve_agent_name_template_reference(name)

    from sase.agent.names._registry import get_reserved_agent_name_map

    current = Path(current_artifacts_dir).expanduser().resolve(strict=False)
    reserved = {
        agent_name
        for agent_name, owner_path in get_reserved_agent_name_map().items()
        if Path(owner_path).expanduser().resolve(strict=False) != current
    }
    return require_latest_agent_name_template(name, names=reserved)

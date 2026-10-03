"""Diagnostics for unresolved macro-shaped references."""

from __future__ import annotations

from difflib import get_close_matches

from sase.macro._literal_zones import literal_zone_ranges
from sase.macro._parsing import (
    extract_known_project_vcs_ref,
    iter_macro_references,
    normalize_vcs_underscore_refs,
)
from sase.macro.models import Macro
from sase.macro.processor import process_macro_references, resolve_macro_aliases


def find_unresolved_reference_names(
    expanded_text: str,
    *,
    extra_macros: dict[str, Macro] | None = None,
) -> tuple[str, ...]:
    """Return unresolved macro-shaped names in already-expanded text."""
    if "#" not in expanded_text:
        return ()

    prompt = resolve_macro_aliases(expanded_text)
    if "#" not in prompt:
        return ()

    prompt = normalize_vcs_underscore_refs(prompt)
    ignored_ranges = literal_zone_ranges(prompt)
    known_names = _known_reference_names(extra_macros=extra_macros)

    unresolved: list[str] = []
    seen: set[str] = set()
    for ref in iter_macro_references(prompt):
        if _in_ignored_range(ref.start, ignored_ranges):
            continue
        if _is_resolved_reference(ref.name, ref.raw, known_names):
            continue
        if ref.name in seen:
            continue
        seen.add(ref.name)
        unresolved.append(ref.name)
    return tuple(unresolved)


def scan_query_for_unresolved_references(query: str) -> tuple[str, ...]:
    """Return unresolved references for a raw launch query.

    This diagnostic is best-effort by design. The real launch path owns
    expansion errors, so failures here never block or alter a launch.
    Expansion uses ``raise_on_error=True`` so a failed expand raises
    ``MacroError`` instead of printing a fatal message that this
    function would then swallow.
    """
    if "#" not in query:
        return ()
    try:
        from sase.agent.multi_prompt import parse_multi_prompt

        multi = parse_multi_prompt(query)
        local_macros = multi.local_macros or None
        unresolved: list[str] = []
        seen: set[str] = set()
        for segment in multi.segments:
            expanded = process_macro_references(
                segment,
                extra_macros=local_macros,
                raise_on_error=True,
            )
            for name in find_unresolved_reference_names(
                expanded,
                extra_macros=local_macros,
            ):
                if name in seen:
                    continue
                seen.add(name)
                unresolved.append(name)
        return tuple(unresolved)
    except (Exception, SystemExit):
        return ()


def format_unresolved_reference_warning(
    name: str,
    *,
    known_names: set[str] | None = None,
) -> str:
    """Return a human-readable warning for one unresolved reference name."""
    names = known_names if known_names is not None else _known_reference_names()
    suggestion = _closest_name(name, names)
    if suggestion:
        return (
            f"unknown xprompt reference '#{name}' will be passed to the agent "
            f"as literal text (did you mean '#{suggestion}'? run "
            "'sase xprompt list' to see available names)"
        )
    return (
        f"unknown xprompt reference '#{name}' will be passed to the agent "
        "as literal text (run 'sase xprompt list' to see available names)"
    )


def format_unresolved_references_toast(names: tuple[str, ...]) -> str:
    """Return an aggregated TUI warning message."""
    refs = ", ".join(f"#{name}" for name in names)
    return f"Unknown xprompt reference(s): {refs} - passed through as literal text"


def _known_reference_names(
    *,
    extra_macros: dict[str, Macro] | None = None,
) -> set[str]:
    from sase.macro.loader import get_all_prompts

    names = set(get_all_prompts())
    if extra_macros:
        names.update(extra_macros)
    return names


def _is_resolved_reference(name: str, raw: str, known_names: set[str]) -> bool:
    if name in known_names:
        return True
    if _is_vcs_reference(name, raw):
        return True
    return _is_agent_resume_reference(name)


def _is_vcs_reference(name: str, raw: str) -> bool:
    from sase.workspace_provider import get_ref_patterns, get_workflow_names

    if name in get_workflow_names():
        for pattern in get_ref_patterns().values():
            if pattern.search(f"{raw} "):
                return True
    return extract_known_project_vcs_ref(f"{raw} ") is not None


def _is_agent_resume_reference(name: str) -> bool:
    return name in {"fork", "resume"}


def _closest_name(name: str, names: set[str]) -> str | None:
    matches = get_close_matches(name, sorted(names), n=1, cutoff=0.78)
    return matches[0] if matches else None


def _in_ignored_range(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


__all__ = [
    "find_unresolved_reference_names",
    "format_unresolved_reference_warning",
    "format_unresolved_references_toast",
    "scan_query_for_unresolved_references",
]

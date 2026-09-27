"""Lineage inheritance for the ``%tab`` directive.

An agent, gate, or monitor turn whose presentation root has a named tab runs
with ``SASE_AGENT_TAB=<name>``. Agent-initiated launches insert
``%tab:<name>`` into each launched prompt (or multi-prompt segment) so the
children land on the same tab. This module holds the pure text helpers; the
export sites live next to ``SASE_AGENT_NAME`` in ``axe/`` and the turn
supervisors.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from ._directive_types import _DIRECTIVE_ALIASES
from ._disabled_regions import protect_disabled_regions, unprotect_disabled_regions
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_paren_for_args, parse_args
from ._prompt_segments import split_prompt_segments

SASE_AGENT_TAB_ENV = "SASE_AGENT_TAB"

__all__ = [
    "SASE_AGENT_TAB_ENV",
    "apply_inherited_agent_tab",
    "inherited_agent_tab",
    "segment_has_active_tab_directive",
    "segment_is_session_attach",
    "set_agent_tab_directive",
]


def inherited_agent_tab(
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return the validated ``SASE_AGENT_TAB`` name, or None when absent.

    Invalid values never propagate: a stored tab is always canonical, so an
    unparsable value is ambient noise and inheritance stays off.
    """
    raw = (env or os.environ).get(SASE_AGENT_TAB_ENV, "")
    candidate = raw.strip().lower()
    if not candidate:
        return None
    try:
        from sase.core.agent_tab import canonicalize_agent_tab
    except Exception:  # noqa: BLE001 - inheritance stays off without the core.
        return None
    try:
        stored = canonicalize_agent_tab(candidate)
    except (ValueError, TypeError):
        return None
    return stored


def segment_has_active_tab_directive(segment: str) -> bool:
    """Return whether *segment* already carries any active ``%tab`` form."""
    return _scan_segment(segment, "tab") is not None


def segment_is_session_attach(segment: str) -> bool:
    """Return whether *segment* is a session attach (``%id(..., session=...)``)."""
    if "session" not in segment:
        return False
    from ._directive_types import _DIRECTIVE_PATTERN

    import re

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(segment, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)
    for match in re.finditer(_DIRECTIVE_PATTERN, protected):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != "id" or match.group(2) is None:
            continue
        paren_end = find_matching_paren_for_args(protected, match.end() - 1)
        if paren_end is None:
            continue
        try:
            _, named_args = parse_args(
                protected[match.end() : paren_end],
                reject_duplicate_named_args=False,
            )
        except Exception:  # noqa: BLE001 - malformed args belong to the launcher.
            continue
        if "session" in named_args:
            return True
    return False


def apply_inherited_agent_tab(prompt: str, tab: str | None) -> str:
    """Insert ``%tab:<tab>`` into each segment of *prompt* that needs it.

    A segment is skipped when it already has any ``%tab`` (including
    ``%tab:main``) or is a session attach, which inherits the session root's
    tab with a mismatch error on explicit disagreement. The operation is
    idempotent: re-applying a prompt that already carries the tab is a no-op.
    """
    if not tab:
        return prompt
    segments, _ = split_prompt_segments(prompt)
    if len(segments) == 1:
        return _apply_to_segment(prompt, tab)
    # The bead-work renderer joins clean segments with a bare ``---`` line;
    # strip the split framing newlines first so changed prompts rejoin in
    # that same canonical form.
    stripped = [segment.strip("\n") for segment in segments]
    applied = [_apply_to_segment(segment, tab) for segment in stripped]
    if applied == stripped:
        return prompt
    return "\n---\n".join(applied)


def _apply_to_segment(segment: str, tab: str) -> str:
    if segment_has_active_tab_directive(segment):
        return segment
    if segment_is_session_attach(segment):
        return segment
    body = segment.lstrip("\n")
    prefix = segment[: len(segment) - len(body)]
    return f"{prefix}%tab:{tab}\n{body}" if body.strip() else f"{prefix}%tab:{tab}"


def set_agent_tab_directive(prompt: str, tab: str | None) -> str:
    """Return *prompt* with one leading ``%tab:<tab>`` directive.

    Existing active tab directives are removed first, so UI callers can
    replace the tab without tripping the duplicate-``%tab`` launcher error.
    Pass None to strip the directive without adding one.
    """
    cleaned = prompt
    scan = _scan_segment(prompt, "tab")
    while scan is not None:
        cleaned = scan.prompt
        scan = _scan_segment(cleaned, "tab")
    if tab is None:
        return cleaned.lstrip("\n")
    body = cleaned.lstrip("\n")
    return f"%tab:{tab}" if not body.strip() else f"%tab:{tab}\n{body}"


class _TabScan:
    """Minimal scan result mirroring ``DispatchDirectiveScan``."""

    __slots__ = ("prompt", "source")

    def __init__(self, prompt: str, source: str) -> None:
        self.prompt = prompt
        self.source = source


def _scan_segment(segment: str, directive: str) -> _TabScan | None:
    """Return the first active *directive* occurrence and the stripped text."""
    if f"%{directive}" not in segment:
        return None
    from ._directive_types import _DIRECTIVE_PATTERN

    import re

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(segment, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)
    regions_to_remove: list[tuple[int, int]] = []
    source = ""
    found = False
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != directive:
            continue
        match_end = match.end()
        if match.group(2) is not None:
            paren_end = find_matching_paren_for_args(protected, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        if not found:
            source = protected[match.start() : match_end]
            found = True
        regions_to_remove.append((match.start(), match_end))
    if not found:
        return None
    cleaned = protected
    for start, end in reversed(regions_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    cleaned = re.sub(r"^\s*\n", "", cleaned)
    return _TabScan(prompt=cleaned, source=source)

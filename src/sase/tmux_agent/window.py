"""Pure window-naming rules for tmux Agent windows.

Ports the two naming rules from the ``tmux_ai_window`` shell script and its
``tm-renumber-ai-windows`` companion: choosing the next free window name, and
planning the renumber that keeps a base's windows reading ``base``, ``base2``,
``base3``, ... with no gaps. The actual tmux calls that apply a plan live in
the ``launcher`` phase.
"""

from __future__ import annotations

from collections.abc import Sequence
import re


def next_window_name(base: str, existing: Sequence[str]) -> str:
    """Return the next free window name for *base* given *existing* names.

    If no window matches ``^<base>[0-9]*$``, returns *base*. Otherwise returns
    ``<base><n>`` for the smallest ``n >= 2`` not already taken.
    """
    pattern = re.compile(rf"^{re.escape(base)}([0-9]*)$")
    matched_any = False
    taken: set[int] = set()
    for name in existing:
        match = pattern.match(name)
        if match is None:
            continue
        matched_any = True
        suffix = match.group(1)
        taken.add(1 if suffix == "" else int(suffix))

    if not matched_any:
        return base

    candidate = 2
    while candidate in taken:
        candidate += 1
    return f"{base}{candidate}"


def renumber_plan(
    base: str,
    windows: Sequence[tuple[int, str]],
) -> tuple[tuple[int, str], ...]:
    """Return the ``(index, new_name)`` renames needed to close gaps in *base*.

    *windows* is ``(window_index, window_name)`` pairs; only names matching
    ``^<base>[0-9]*$`` participate. Matching windows are renumbered in
    ascending window-index order to read ``base``, ``base2``, ``base3``, ...
    with no gaps. Idempotent: a window already carrying its target name is
    omitted from the result.
    """
    pattern = re.compile(rf"^{re.escape(base)}[0-9]*$")
    matching = sorted(
        (pair for pair in windows if pattern.match(pair[1])),
        key=lambda pair: pair[0],
    )

    renames: list[tuple[int, str]] = []
    for position, (index, name) in enumerate(matching):
        new_name = base if position == 0 else f"{base}{position + 1}"
        if new_name != name:
            renames.append((index, new_name))
    return tuple(renames)


__all__ = [
    "next_window_name",
    "renumber_plan",
]

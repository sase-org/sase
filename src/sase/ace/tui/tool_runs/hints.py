"""``v`` hint-mode targets for retained tool-run logs (``runs-card-anatomy``).

One ``⚒ run log <8hex>`` target per visible run block. Targets ride
``_hint_mappings`` as ``toolrun-log:<run_id>`` pseudo-targets (real
hint targets are filesystem paths, so the prefix never collides),
mirroring the ``bead:`` scheme in
``sase.ace.tui.bead_hint_targets``. Selecting one opens the retained
log in the pager as a text section; the tail read runs off-thread at
the call site, like ``build_pager_document``.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Iterable, Mapping

#: Pseudo-target prefix for retained-log hint targets (never a real path).
TOOLRUN_LOG_TARGET_PREFIX = "toolrun-log:"


def _tool_run_log_hint_target(run_id: str) -> str | None:
    """Return the ``toolrun-log:<run_id>`` target, or None when blank."""

    clean = str(run_id or "").strip()
    if not clean:
        return None
    return f"{TOOLRUN_LOG_TARGET_PREFIX}{clean}"


def run_id_from_hint_target(target: str) -> str | None:
    """Return the run id carried by a ``toolrun-log:`` target, if any."""

    if not isinstance(target, str):
        return None
    if not target.startswith(TOOLRUN_LOG_TARGET_PREFIX):
        return None
    run_id = target[len(TOOLRUN_LOG_TARGET_PREFIX) :].strip()
    return run_id or None


def _run_log_hint_label(run_id: str) -> str:
    """Return the ``⚒ run log <8hex>`` label for one run block."""

    return f"⚒ run log {str(run_id or '')[:8]}"


def visible_tool_run_log_targets(
    blocks: Iterable[Any],
) -> list[tuple[str, str]]:
    """Return ``(label, target)`` pairs for visible run blocks in order.

    Accepts card blocks (``block_id``) and summary rows (``run_id``);
    block order is preserved and duplicates collapse.
    """

    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for block in blocks or ():
        run_id = str(getattr(block, "block_id", "") or "").strip()
        if not run_id:
            run_id = str(getattr(block, "run_id", "") or "").strip()
        if not run_id or run_id in seen:
            continue
        target = _tool_run_log_hint_target(run_id)
        if target is None:
            continue
        seen.add(run_id)
        entries.append((_run_log_hint_label(run_id), target))
    return entries


def hint_number_for_tool_run(
    mappings: Mapping[int, str] | None, run_id: str
) -> int | None:
    """Return the hint number mapped to *run_id*'s log target, if any."""

    if not mappings or not run_id:
        return None
    want = _tool_run_log_hint_target(run_id)
    for number, target in mappings.items():
        if target == want:
            return int(number)
    return None


def build_tool_run_log_pager_document(
    run_id: str,
    label: str,
    tail_lines: Iterable[str],
    *,
    availability: str = "available",
    truncated: bool = False,
) -> Any:
    """Assemble a pager document for one retained run log (text section).

    Takes the already-read tail lines; callers read them off-thread
    through the detail loader or ``tool_run_log_tail`` first.
    """

    from sase.pager.document import PagerDocument, PagerSection
    from sase.pager.link_scan import PagerOrigin

    lines = [str(line) for line in (tail_lines or ())]
    if not lines:
        body = "(no log recorded)"
    else:
        body = "\n".join(lines)
    title = f"⚒ run log {label} {str(run_id or '')[:8]}"
    if truncated or availability == "truncated":
        title += " · truncated"
    section = PagerSection(
        identity=f"toolrun-log-{str(run_id or '')[:8]}",
        title=title,
        kind="text",
        body=body,
        origin=PagerOrigin.AGENT,
    )
    return PagerDocument(
        sections=(section,),
        title=title,
        origin=PagerOrigin.AGENT,
    )


__all__ = [
    "TOOLRUN_LOG_TARGET_PREFIX",
    "build_tool_run_log_pager_document",
    "hint_number_for_tool_run",
    "run_id_from_hint_target",
    "visible_tool_run_log_targets",
]

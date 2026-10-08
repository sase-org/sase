"""Fold, callout cache, tint, and scroll target for the plan document pane.

No Textual imports. Keypress paths only read the cached spans and the
fold map; they never validate, lex, or stat.
"""

from __future__ import annotations

from typing import Any


def fold_plan_decisions_content(
    content: str,
) -> tuple[str, dict[int, int], int | None, int]:
    """Fold a ``decisions:`` YAML map into one dim line.

    Returns ``(folded, raw_to_folded, folded_decision_line, count)``.
    ``e`` and ``Y`` callers keep the raw ``content``; only the display
    uses ``folded``.
    """
    from sase.sdd.frontmatter import parse_frontmatter

    try:
        frontmatter, _body, had = parse_frontmatter(content)
    except Exception:
        return content, {}, None, 0
    if not had or "decisions" not in frontmatter:
        return content, {}, None, 0
    decisions = frontmatter["decisions"]
    count = len(decisions) if isinstance(decisions, dict) else 0
    if not count:
        return content, {}, None, 0
    lines = content.splitlines()
    # Find frontmatter bounds: first line --- and closing ---.
    if not lines or lines[0].strip() != "---":
        return content, {}, None, 0
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        return content, {}, None, 0
    # Find the decisions: key line inside frontmatter.
    decisions_start = None
    for index in range(1, closing):
        stripped = lines[index].split("#", 1)[0]
        if stripped.strip().startswith("decisions:"):
            # Only top-level decisions: key (no indent).
            indent = len(lines[index]) - len(lines[index].lstrip())
            if indent == 0:
                decisions_start = index
                break
    if decisions_start is None:
        return content, {}, None, 0
    # The map runs until the next top-level key or the closing fence.
    decisions_end = decisions_start
    for index in range(decisions_start + 1, closing):
        line = lines[index]
        if not line.strip() or line.strip().startswith("#"):
            decisions_end = index
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and ":" in line:
            break
        decisions_end = index
    folded_line = f"decisions: {count} · answered in the Decisions panel"
    folded_lines = lines[:decisions_start] + [folded_line] + lines[decisions_end + 1 :]
    folded = "\n".join(folded_lines)
    if content.endswith("\n"):
        folded += "\n"
    raw_to_folded: dict[int, int] = {}
    for raw in range(len(lines)):
        if raw < decisions_start:
            raw_to_folded[raw] = raw
        elif raw <= decisions_end:
            raw_to_folded[raw] = decisions_start
        else:
            raw_to_folded[raw] = raw - (decisions_end - decisions_start)
    return folded, raw_to_folded, decisions_start, count


def cache_callout_spans(content: str, tier: str = "tale") -> list[dict[str, Any]]:
    """Cache decision callout spans once for displayed content.

    Uses ``validate_plan`` in launch mode. Never raises; failures yield
    an empty cache. Callers must not call this on a keypress.
    """
    try:
        from sase.sdd.plan_validate import validate_plan
    except Exception:
        return []
    try:
        result = validate_plan(content, tier, mode="launch")
    except Exception:
        return []
    plan = getattr(result, "plan", None)
    callouts = getattr(plan, "decision_callouts", ()) if plan is not None else ()
    spans: list[dict[str, Any]] = []
    for callout in callouts or ():
        try:
            spans.append(
                {
                    "id": str(getattr(callout, "id", "")),
                    "key": getattr(callout, "key", None),
                    "branch": str(getattr(callout, "branch", "")),
                    "start_line": int(getattr(callout, "start_line", 0)),
                    "end_line": int(getattr(callout, "end_line", 0)),
                }
            )
        except Exception:
            continue
    return spans


def scroll_target_for_decision(
    decision_id: str,
    callouts: list[dict[str, Any]],
    content: str,
    raw_to_folded: dict[int, int] | None = None,
) -> int | None:
    """Return the folded line to scroll to for one decision.

    Prefers its first callout span, else the first mention of its id.
    Raw lines are mapped through the fold; callers scroll with the
    folded coordinate.
    """
    key = str(decision_id)
    for span in callouts or []:
        if not isinstance(span, dict) or str(span.get("id", "")) != key:
            continue
        try:
            raw = int(span.get("start_line", 0))
        except Exception:
            continue
        # Core lines are 1-based; fold map is 0-based.
        raw_index = max(0, raw - 1)
        if raw_to_folded is not None:
            return raw_to_folded.get(raw_index, raw_index)
        return raw_index
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if key and key in line:
            if raw_to_folded is not None:
                return raw_to_folded.get(index, index)
            return index
    return None


def classify_callout(span: dict[str, Any], values: dict[str, Any]) -> str:
    """Classify one callout span as ``chosen`` or ``dimmed``.

    A toggle callout answered no is dimmed. Never hides a branch.
    """
    decision_id = str(span.get("id", ""))
    branch = span.get("branch")
    key = span.get("key")
    value = values.get(decision_id)
    if isinstance(value, bool):
        # Toggle: a callout answered no dims; answered yes is chosen.
        return "chosen" if value is True else "dimmed"
    if key is not None and value is not None:
        return "chosen" if str(key) == str(value) else "dimmed"
    if branch is not None and value is not None:
        return "chosen" if str(branch) == str(value) else "dimmed"
    return "dimmed"


__all__ = [
    "cache_callout_spans",
    "classify_callout",
    "fold_plan_decisions_content",
    "scroll_target_for_decision",
]

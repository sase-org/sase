"""Pure name vocabulary for the node rail.

No Textual imports, no disk I/O. Cell math uses ``rich.cells.cell_len``
so wide characters budget correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.cells import cell_len
from sase.agent.status_buckets import agent_status_bucket

from ..models._agent_tree import agent_tree_title
from ..models.agent_status import STOPPED_STATUS
from ._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _AGENT_SESSION_NAME_STYLE,
    _CLAN_NAME_STYLE,
    _NAMED_PROC_ROW_STYLE,
)

if TYPE_CHECKING:
    from ..models.agent import Agent

#: Expanded left-title color reused for rail fallback names.
RAIL_FALLBACK_NAME_STYLE = "#00D7AF"

_NAMED_STEP_TYPES = frozenset({"bash", "python"})


def rail_row_name(agent: Agent) -> tuple[str, str]:
    """Return the rail ``(name, style)`` identity token for *agent*.

    Resolution order mirrors the expanded row's identity token:

    1. named procs and bash/python workflow steps: ``agent_tree_title``;
    2. clan containers: ``display_name`` in the clan color;
    3. ``presented_agent_name or agent_name`` (session containers in the
       session color, everything else in gold);
    4. fallback ``agent_tree_title or display_name`` in title teal.
    """
    if agent.is_named_proc:
        title = agent_tree_title(agent)
        if title:
            return (title, _NAMED_PROC_ROW_STYLE)
    elif agent.is_workflow_step_child and agent.step_type in _NAMED_STEP_TYPES:
        title = agent_tree_title(agent)
        if title:
            return (title, RAIL_FALLBACK_NAME_STYLE)
    if agent.is_clan_container:
        return (agent.display_name, _CLAN_NAME_STYLE)
    presented = agent.presented_agent_name or agent.agent_name
    if presented:
        if agent.is_agent_session_container_row:
            return (presented, _AGENT_SESSION_NAME_STYLE)
        return (presented, _AGENT_NAME_ANNOTATION_STYLE)
    fallback = agent_tree_title(agent) or agent.display_name
    if fallback:
        return (fallback, RAIL_FALLBACK_NAME_STYLE)
    return ("", RAIL_FALLBACK_NAME_STYLE)


def rail_name_is_dimmed(agent: Agent, *, is_unread: bool) -> bool:
    """Return whether *agent*'s rail name renders dim.

    Settled and read means the ``Done`` bucket and not unread, or raw
    ``STOPPED``. Mirrors the existing dim-``✓`` rule.
    """
    if agent.status == STOPPED_STATUS:
        return True
    try:
        settled = agent_status_bucket(agent) == "Done"
    except Exception:
        settled = False
    return bool(settled and not is_unread)


def _take_cells(text: str, budget: int) -> str:
    """Return the longest head of *text* within *budget* cells."""
    if budget <= 0:
        return ""
    if cell_len(text) <= budget:
        return text
    out: list[str] = []
    used = 0
    for char in text:
        width = cell_len(char)
        if used + width > budget:
            break
        out.append(char)
        used += width
    return "".join(out)


def _take_cells_tail(text: str, budget: int) -> str:
    """Return the longest tail of *text* within *budget* cells."""
    if budget <= 0:
        return ""
    if cell_len(text) <= budget:
        return text
    out: list[str] = []
    used = 0
    for char in reversed(text):
        width = cell_len(char)
        if used + width > budget:
            break
        out.append(char)
        used += width
    return "".join(reversed(out))


def rail_middle_elide(text: str, budget: int) -> str:
    """Elide *text* with a middle ``…`` to fit *budget* cells.

    Keeps about 40% of the head and 60% of the tail, since sase names
    differ at the end (``.land``, ``--plan``, ``.cld``). Cell-aware for
    wide characters. Returns *text* unchanged when it already fits;
    a non-positive budget yields ``""``.
    """
    if budget <= 0:
        return ""
    if cell_len(text) <= budget:
        return text
    if budget == 1:
        return "…"
    head_budget = round((budget - 1) * 0.4)
    tail_budget = (budget - 1) - head_budget
    head = _take_cells(text, head_budget)
    tail = _take_cells_tail(text, tail_budget)
    return f"{head}…{tail}"


__all__ = [
    "RAIL_FALLBACK_NAME_STYLE",
    "rail_middle_elide",
    "rail_name_is_dimmed",
    "rail_row_name",
]

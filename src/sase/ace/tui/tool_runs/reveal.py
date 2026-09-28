"""Shared "reveal a run's block" helper (sase-1bt land tale, step A).

Resolves the owning local row owner-first, navigates with the Node Finder
ladder, shows the Tools deck, activates the Runs card, and selects the run's
block. Pending selection survives the Tools document worker load.
Pure except for app navigation calls; never touches SQLite, stat, or logs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_tool_run_owner_predicate(
    agent: str | None,
    owner_kind: str | None,
    owner_id: str | None,
) -> Callable[[Any], bool]:
    """Return a row predicate matching the run's owning node, owner first."""

    want_agent = str(agent or "").strip()
    want_kind = str(owner_kind or "").strip()
    want_id = str(owner_id or "").strip()

    def _matches(row: Any) -> bool:
        try:
            if getattr(row, "fleet_origin_alias", None):
                return False
            if want_kind == "monitor" and want_id:
                return bool(
                    getattr(row, "is_monitor", False)
                    and getattr(row, "monitor_id", None) == want_id
                )
            if want_kind == "proc" and want_id:
                return bool(
                    getattr(row, "is_named_proc", False)
                    and getattr(row, "proc_id", None) == want_id
                )
            if not want_agent:
                return False
            return getattr(row, "agent_name", None) == want_agent
        except Exception:
            return False

    return _matches


def _selected_agent(app: Any) -> Any | None:
    getter = getattr(app, "_get_selected_agent", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        return None


def _panels_for_tool_runs(app: Any) -> list[Any]:
    panels: list[Any] = []
    test_panels = getattr(app, "_test_tool_run_panels", None)
    if isinstance(test_panels, list) and test_panels:
        return list(test_panels)
    area = getattr(app, "deck_area", None)
    if area is not None:
        for method in ("focused_panel", "visible_panels"):
            try:
                getter = getattr(area, method, None)
                if not callable(getter):
                    continue
                found = getter()
                if method == "focused_panel":
                    if found is not None:
                        panels.append(found)
                    break
                for panel in found or ():
                    panels.append(panel)
                if panels:
                    break
            except Exception:
                continue
        if panels:
            return panels
    query = getattr(app, "query", None)
    if callable(query):
        try:
            from sase.ace.tui.widgets.decks.panel import DeckPanel

            found = query(DeckPanel)
            items = list(found) if found is not None else []
            if items:
                return items
        except Exception:
            pass
    single = getattr(app, "_test_tool_run_panel", None)
    if single is not None:
        return [single]
    return []


def _show_tools_deck(app: Any) -> None:
    show_card = getattr(app, "action_show_tool_runs_card", None)
    if callable(show_card):
        try:
            show_card()
        except Exception:
            pass
    try:
        from sase.ace.tui.actions.agents._notification_handlers import (
            show_tools_deck_best_effort,
        )

        show_tools_deck_best_effort(app)
    except Exception:
        pass


def _activate_runs_card(panel: Any) -> None:
    show = getattr(panel, "_show_tools_card", None)
    if callable(show):
        try:
            show("runs")
        except Exception:
            pass


def _is_single_run_document(panel: Any, n_runs: int | None = None) -> bool:
    if n_runs == 1:
        return True
    try:
        doc = getattr(panel, "_tool_runs_document", None)
        cards: Any = getattr(doc, "cards", None) or ()
        if len(cards) == 1:
            blocks: Any = getattr(cards[0], "blocks", None) or ()
            if len(blocks) <= 1:
                try:
                    from sase.ace.tui.widgets.decks.spec import DeckId

                    avail = getattr(panel, "_availability", {}).get(DeckId.TOOLS)
                    if (
                        avail is not None
                        and int(getattr(avail, "runs_count", 0) or 0) == 1
                    ):
                        return True
                except Exception:
                    pass
                if len(blocks) == 0:
                    return True
    except Exception:
        pass
    return False


def _try_select_on_panel(panel: Any, run_id: str) -> bool:
    select = getattr(panel, "select_block", None)
    if callable(select):
        try:
            if bool(select(run_id)):
                return True
        except Exception:
            pass
    try:
        from sase.ace.tui.widgets.decks.spec import DeckId

        doc_select = getattr(panel, "select_document_block", None)
        if callable(doc_select):
            try:
                if bool(doc_select(DeckId.TOOLS, run_id)):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    if _is_single_run_document(panel):
        return True
    return False


def _store_pending_tool_run(app: Any, run_id: str, identity: Any | None) -> None:
    try:
        app._pending_tool_run_block = {"run_id": run_id, "identity": identity}  # type: ignore[attr-defined]
    except Exception:
        pass


def _drop_pending_tool_run(app: Any) -> None:
    try:
        app._pending_tool_run_block = None  # type: ignore[attr-defined]
    except Exception:
        pass


def _pending_tool_run(app: Any) -> dict[str, Any] | None:
    try:
        pending = getattr(app, "_pending_tool_run_block", None)
    except Exception:
        return None
    return dict(pending) if isinstance(pending, dict) else None


def apply_pending_tool_run_select(
    app: Any, panel: Any, *, n_runs: int | None = None
) -> bool:
    """Apply the pending run selection to *panel* once its document lands."""

    pending = _pending_tool_run(app)
    if not pending:
        return False
    run_id = str(pending.get("run_id") or "")
    if not run_id:
        _drop_pending_tool_run(app)
        return False
    try:
        current = _selected_agent(app)
        want_identity = pending.get("identity")
        if want_identity is not None and current is not None:
            try:
                if getattr(current, "identity", None) != want_identity:
                    _drop_pending_tool_run(app)
                    return False
            except Exception:
                pass
    except Exception:
        pass
    try:
        if bool(_try_select_on_panel(panel, run_id)):
            _drop_pending_tool_run(app)
            return True
    except Exception:
        pass
    if n_runs == 1 or _is_single_run_document(panel, n_runs):
        _drop_pending_tool_run(app)
        return True
    return False


def reveal_tool_run_block(
    app: Any,
    run_id: str,
    *,
    agent: str | None = None,
    owner_kind: str | None = None,
    owner_id: str | None = None,
) -> bool:
    """Reveal *run_id*'s Runs block; return True when the block is selected.

    Owner-first row matching reuses the shared predicate (no copy). The
    currently selected node takes the same-node path (deck + card + block
    only). Otherwise the row is resolved with ``resolve_loaded_agent`` and
    navigated with ``jump_to_loaded_agent``. No SQLite, stat, or log I/O.
    """

    clean = str(run_id or "").strip()
    if not clean:
        return False
    predicate = build_tool_run_owner_predicate(agent, owner_kind, owner_id)
    try:
        from sase.ace.tui.actions.agents._notification_navigation import (
            jump_to_loaded_agent,
            resolve_loaded_agent,
        )
    except Exception:
        return False

    current = _selected_agent(app)
    same_node = False
    try:
        same_node = current is not None and bool(predicate(current))
    except Exception:
        same_node = False
    target = current if same_node else None
    if not same_node:
        try:
            target = resolve_loaded_agent(app, predicate)
        except Exception:
            target = None
        if target is None:
            name = str(agent or owner_id or clean[:8])
            try:
                app.notify(f"No agent row for {name}", severity="warning")  # type: ignore[attr-defined]
            except Exception:
                pass
            return False
        try:
            if not bool(jump_to_loaded_agent(app, target)):
                return False
        except Exception:
            return False
    try:
        identity = getattr(target if target is not None else current, "identity", None)
    except Exception:
        identity = None
    _show_tools_deck(app)
    panels = _panels_for_tool_runs(app)
    if not panels:
        _store_pending_tool_run(app, clean, identity)
        return True
    selected = False
    for panel in panels:
        try:
            _activate_runs_card(panel)
        except Exception:
            pass
        try:
            if _try_select_on_panel(panel, clean):
                selected = True
                break
        except Exception:
            continue
    if selected:
        _drop_pending_tool_run(app)
        try:
            if _is_single_run_document(panels[0]):
                _drop_pending_tool_run(app)
        except Exception:
            pass
        return True
    _store_pending_tool_run(app, clean, identity)
    return True


def reveal_selected_node_run(app: Any, run_id: str) -> bool:
    """Reveal *run_id* on the currently selected node (click/hint path).

    Skips row navigation; shows the Tools deck, activates the Runs card,
    and selects the block. Holds pending when the document is partial.
    No SQLite, stat, or log I/O.
    """

    clean = str(run_id or "").strip()
    if not clean:
        return False
    current = _selected_agent(app)
    try:
        identity = getattr(current, "identity", None) if current is not None else None
    except Exception:
        identity = None
    _show_tools_deck(app)
    panels = _panels_for_tool_runs(app)
    if not panels:
        _store_pending_tool_run(app, clean, identity)
        return True
    for panel in panels:
        try:
            _activate_runs_card(panel)
        except Exception:
            pass
        try:
            if _try_select_on_panel(panel, clean):
                _drop_pending_tool_run(app)
                return True
        except Exception:
            continue
    _store_pending_tool_run(app, clean, identity)
    return True


def run_id_from_click_meta(event: Any) -> str | None:
    """Return the run id stamped on a click event's style meta, if any."""

    try:
        from sase.ace.tui.tool_runs.links_jumps import TOOLRUN_JUMP_META_KEY
    except Exception:
        return None
    try:
        style = getattr(event, "style", None)
        meta = getattr(style, "meta", None)
        if isinstance(meta, dict) and TOOLRUN_JUMP_META_KEY in meta:
            run_id = str(meta.get(TOOLRUN_JUMP_META_KEY) or "").strip()
            return run_id or None
    except Exception:
        return None
    return None


__all__ = [
    "apply_pending_tool_run_select",
    "build_tool_run_owner_predicate",
    "reveal_selected_node_run",
    "reveal_tool_run_block",
    "run_id_from_click_meta",
]

"""Continue or Close a stranded bead from Agents Enter or Beads ``w``."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sase.ace.tui.models.agent_stranded import force_stranded_refresh
from sase.ace.tui.models.stranded_resolve import (
    StrandedResolveResult,
    build_stranded_resolve_view,
    stranded_continue_prompt,
)
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task

if TYPE_CHECKING:
    from sase.ace.tui.modals.bead_close_modal import BeadCloseResult
    from sase.bead.model import Issue


def open_stranded_resolve_modal(app: Any, project: str, bead_id: str) -> None:
    """Mount the resolve modal from the warm cache. No disk I/O."""
    view = build_stranded_resolve_view(project, bead_id)
    if view is None:
        notify = getattr(app, "notify", None)
        if callable(notify):
            notify("Stranded work is still loading", severity="warning")
        return
    from sase.ace.tui.modals.stranded_resolve_modal import StrandedResolveModal

    def dismissed(result: StrandedResolveResult | None) -> None:
        if result is None:
            return
        if result.choice == "continue":
            _continue_stranded_leaf(app, result.project, result.leaf_id)
            return
        _close_stranded_leaf(app, result.project, result.leaf_id)

    app.push_screen(StrandedResolveModal(view), dismissed)


def schedule_stranded_resolve_refresh(app: Any, project: str) -> None:
    """Expire the TTL and schedule Agents plus Beads stranded warmups."""
    force_stranded_refresh(project)
    schedule = getattr(app, "_schedule_bead_confirmation_warmup", None)
    if callable(schedule):
        schedule(source="stranded_resolve")
    pane_getter = getattr(app, "_beads_pane", None)
    pane = pane_getter() if callable(pane_getter) else None
    if pane is None:
        return
    refresh = getattr(pane, "_schedule_stranded_refresh", None)
    if callable(refresh):
        refresh(force=True)


def _continue_stranded_leaf(app: Any, project: str, leaf_id: str) -> None:
    view = build_stranded_resolve_view(project, leaf_id)
    notify = getattr(app, "notify", None)
    if view is None:
        if callable(notify):
            notify("Stranded work is no longer flagged", severity="warning")
        return
    leaf = next(
        (item for item in view.leaves if item.bead_id == leaf_id),
        view.selected_leaf,
    )
    if leaf.continue_disabled_reason or not leaf.last_turn:
        if callable(notify):
            notify(
                leaf.continue_disabled_reason or "No last turn to fork",
                severity="warning",
            )
        return
    last_turn = leaf.last_turn
    cause = leaf.cause
    agent = _find_loaded_agent(app, last_turn)
    tab_name: str | None = None
    if agent is not None:
        candidate = getattr(agent, "agent_tab", None)
        if isinstance(candidate, str) and candidate:
            tab_name = candidate
    prepare = getattr(app, "_run_prompt_vcs_preparation", None)
    if agent is not None and callable(prepare):
        from .agents._fork_scope import (
            agent_prompt_target_scope,
            resolve_prompt_target_scope_vcs_tag,
        )

        scope = agent_prompt_target_scope(agent, last_turn, history_fallback="fork")
        agents_snapshot = tuple(getattr(app, "_agents", ()) or ())

        def on_complete(vcs_tag: str | None) -> None:
            _open_continue_prompt(
                app,
                leaf_id=leaf_id,
                last_turn=last_turn,
                cause=cause,
                vcs_tag=vcs_tag,
                tab_name=tab_name,
            )

        prepare(
            lambda: resolve_prompt_target_scope_vcs_tag(scope, agents_snapshot),
            on_complete,
            worker_name="agent-stranded-continue",
            failure_message="Unable to prepare continue prompt",
        )
        schedule_stranded_resolve_refresh(app, project)
        return
    _open_continue_prompt(
        app,
        leaf_id=leaf_id,
        last_turn=last_turn,
        cause=cause,
        vcs_tag=None,
        tab_name=tab_name,
    )
    schedule_stranded_resolve_refresh(app, project)


def _open_continue_prompt(
    app: Any,
    *,
    leaf_id: str,
    last_turn: str,
    cause: str,
    vcs_tag: str | None,
    tab_name: str | None,
) -> None:
    show = getattr(app, "_show_prompt_input_bar_for_home", None)
    if not callable(show):
        notify = getattr(app, "notify", None)
        if callable(notify):
            notify("The prompt bar is unavailable", severity="warning")
        return
    show(
        initial_text=stranded_continue_prompt(
            leaf_id=leaf_id,
            last_turn=last_turn,
            cause=cause,
            vcs_tag=vcs_tag,
            tab_name=tab_name,
        ),
        display_name=f"continue({leaf_id})",
        history_sort_key=last_turn,
    )


def _close_stranded_leaf(app: Any, project: str, leaf_id: str) -> None:
    async def _load() -> None:
        try:
            payload = await asyncio.to_thread(
                _load_bead_close_context, project, leaf_id
            )
        except Exception as exc:
            notify = getattr(app, "notify", None)
            if callable(notify):
                notify(f"Couldn't load {leaf_id}: {exc}", severity="warning")
            return
        _finish_close_load(app, project, leaf_id, payload)

    task = spawn_pump_free_task(
        app,
        _load(),
        name="sase-stranded-close-load",
        registry_attr="_stranded_resolve_async_tasks",
    )
    if task is not None:
        return
    try:
        payload = _load_bead_close_context(project, leaf_id)
    except Exception as exc:
        notify = getattr(app, "notify", None)
        if callable(notify):
            notify(f"Couldn't load {leaf_id}: {exc}", severity="warning")
        return
    _finish_close_load(app, project, leaf_id, payload)


def _finish_close_load(
    app: Any,
    project: str,
    leaf_id: str,
    payload: tuple[Issue, tuple[str, ...], str] | None,
) -> None:
    notify = getattr(app, "notify", None)
    if payload is None:
        if callable(notify):
            notify(f"Couldn't load {leaf_id}", severity="warning")
        return
    issue, descendants, workspace = payload
    from sase.ace.tui.modals.bead_close_modal import BeadCloseModal

    def dismissed(result: BeadCloseResult | None) -> None:
        if result is None:
            return
        submit = getattr(app, "_submit_bead_close", None)
        if not callable(submit):
            if callable(notify):
                notify("Close is unavailable", severity="warning")
            return
        pane_getter = getattr(app, "_beads_pane", None)
        pane = pane_getter() if callable(pane_getter) else None
        submit(issue, project, workspace, result, pane=pane)

    app.push_screen(
        BeadCloseModal(issue, unclosed_descendants=descendants),
        dismissed,
    )


def _load_bead_close_context(
    project: str, bead_id: str
) -> tuple[Issue, tuple[str, ...], str] | None:
    from sase.bead.model import Status
    from sase.bead.project import BeadProject
    from sase.bead.store_locator import canonical_beads_dir_for_project

    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        return None
    workspace = str(beads_dir.parent)
    with BeadProject(beads_dir.parent, beads_dirname=beads_dir.name) as project_store:
        issue = project_store.show(bead_id)
        issues = project_store.list_issues()
    children: dict[str, list[Issue]] = {}
    for item in issues:
        if item.parent_id:
            children.setdefault(item.parent_id, []).append(item)
    descendants: list[str] = []
    pending = list(children.get(issue.id, ()))
    while pending:
        child = pending.pop(0)
        if child.status is not Status.CLOSED:
            descendants.append(child.id)
        pending.extend(children.get(child.id, ()))
    return issue, tuple(descendants), workspace


def _find_loaded_agent(app: Any, name: str) -> Any | None:
    for bucket in (
        getattr(app, "_agents_with_children", None),
        getattr(app, "_agents", None),
    ):
        if not bucket:
            continue
        for agent in bucket:
            if getattr(agent, "agent_name", None) == name:
                return agent
    return None


__all__ = [
    "open_stranded_resolve_modal",
    "schedule_stranded_resolve_refresh",
]

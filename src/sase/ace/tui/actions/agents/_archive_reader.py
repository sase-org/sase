"""Off-thread Archive bundle hydration and read-only detail paint.

Archive-reader seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
Selection immediately paints the archived identity and a titled loading
placeholder. The existing 150 ms ``DetailPanelDebouncer`` then starts a
pump-free ``load_bundle_file`` worker. Recheck view, selection key, and
generation after every await and before accepting widget output. Hydrated
agents live only on ``ArchiveReaderRuntime`` — never in ``_agents``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...models.agent_archive_reader import (
    ARCHIVE_LOADING_TITLE,
    ARCHIVE_UNREADABLE_TITLE,
    ArchiveReaderRuntime,
    archive_container_summary_text,
    archive_identity_header_from_light_row,
    mark_agent_archive_read_only,
    probe_retained_archive_content,
    resolve_archive_bundle_path,
    titled_archive_card,
)
from ...models.agent_archive_view import (
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    ARCHIVE_ROW_NONE,
    ARCHIVE_SECTION_LIST,
    container_key_of,
)
from ...util.pump_tasks import spawn_pump_free_task
from ._archive_view import (
    archive_detail_owns_panel,
    get_agents_tab_selection,
    remember_agents_detail_owner,
    scheduled_agents_detail_is_current,
)

log = logging.getLogger(__name__)

_RUNTIME_ATTR = "_archive_reader_runtime"
_READER_TASK_NAME = "archive-reader-hydrate"
_READER_TASK_REGISTRY = "_archive_reader_tasks"
_UNREADABLE_DETAIL = "Light-row facts remain available to the Record deck."


def _reader_runtime(owner: Any) -> ArchiveReaderRuntime:
    """Return (and lazily create) the owner's Archive reader runtime."""
    runtime = getattr(owner, _RUNTIME_ATTR, None)
    if not isinstance(runtime, ArchiveReaderRuntime):
        runtime = ArchiveReaderRuntime()
        setattr(owner, _RUNTIME_ATTR, runtime)
    return runtime


def clear_archive_reader_runtime(owner: Any) -> None:
    """Drop a hydrated Archive agent so it cannot leak across a view switch."""
    runtime = getattr(owner, _RUNTIME_ATTR, None)
    if isinstance(runtime, ArchiveReaderRuntime):
        runtime.archive_key = None
        runtime.generation = 0
        runtime.hydrated_agent = None
        runtime.unreadable = False
        runtime.loading = False
        runtime.retained = ()
        runtime.missing = ()
        runtime.bundle_path = None
        runtime.light_row = None


def hydrated_archive_agent_for(owner: Any, key: str | None) -> Any | None:
    """Return the hydrated agent for ``key`` when it still matches the runtime."""
    if not key:
        return None
    runtime = getattr(owner, _RUNTIME_ATTR, None)
    if not isinstance(runtime, ArchiveReaderRuntime):
        return None
    if runtime.archive_key != key:
        return None
    return runtime.hydrated_agent


def _detail_widget(owner: Any) -> Any | None:
    injected = getattr(owner, "_archive_detail_widget", None)
    if injected is not None:
        return injected
    query_one = getattr(owner, "query_one", None)
    if not callable(query_one):
        return None
    from textual.css.query import NoMatches

    from ...widgets import AgentDetail

    try:
        return query_one("#agent-detail-panel", AgentDetail)
    except NoMatches:
        return None
    except Exception:
        return None


def _paint_identity(detail: Any, header: Any) -> None:
    on_header = getattr(detail, "_on_identity_header", None)
    if callable(on_header):
        on_header(header)
        return
    show = getattr(detail, "show_identity", None)
    if callable(show):
        show(header)


def _paint_record_from_light_row(
    owner: Any,
    detail: Any,
    light_row: Mapping[str, Any] | None,
    members: tuple[Mapping[str, Any], ...] = (),
) -> None:
    """Paint every visible RECORD panel from a light-row subject.

    Unreadable entries and container rows have no hydrated Agent. RECORD
    stays available; other decks keep their titled cards. No bundle is
    hydrated per member.
    """
    if detail is None or not light_row:
        return
    try:
        from ...widgets.decks.record.model import record_subject_from_light_row

        state = getattr(owner, "_agents_archive_controller", None)
        subject = record_subject_from_light_row(
            light_row,
            members=members,
            display_snapshot=getattr(state, "display_snapshot", None),
        )
    except Exception:
        return
    try:
        from ...widgets._agent_detail_deck_refresh import AgentDetailDeckRefreshMixin

        if isinstance(detail, AgentDetailDeckRefreshMixin):
            detail.show_record_subject(subject)
            return
    except Exception:
        pass
    show = getattr(detail, "show_record_subject", None)
    if not callable(show):
        return
    try:
        show(subject)
    except Exception:
        log.debug("Record light-row subject paint failed", exc_info=True)


def _show_titled(detail: Any, title: str, detail_text: str = "") -> None:
    show_cause = getattr(detail, "show_tab_empty_state", None)
    if callable(show_cause):
        show_cause(title, detail_text)
        return
    update = getattr(detail, "update", None)
    if callable(update):
        update(titled_archive_card(title, detail_text))
        return
    show_empty = getattr(detail, "show_empty", None)
    if callable(show_empty):
        show_empty()


def paint_archive_detail_placeholder(owner: Any) -> None:
    """Immediately replace identity and earlier agent text with Archive chrome.

    Banners, the pulse, and page tails clear the panel. A container paints a
    Summary over loaded light members (no bundle hydration). A run paints the
    archived identity plus a titled loading card until hydration lands.
    """
    if not archive_detail_owns_panel(owner):
        return
    detail = _detail_widget(owner)
    selection = get_agents_tab_selection(owner)
    runtime = _reader_runtime(owner)
    runtime.archive_key = selection.archive_key
    runtime.generation = getattr(
        getattr(owner, "_agents_archive_view", None), "generation", 0
    )
    runtime.loading = selection.row_kind == ARCHIVE_ROW_AGENT
    runtime.unreadable = False
    runtime.light_row = selection.light_row
    if selection.row_kind == ARCHIVE_ROW_NONE:
        runtime.hydrated_agent = None
        runtime.loading = False
        if detail is not None:
            show_empty = getattr(detail, "show_empty", None)
            if callable(show_empty):
                show_empty()
        return
    if selection.row_kind == ARCHIVE_ROW_CONTAINER:
        runtime.hydrated_agent = None
        runtime.loading = False
        _paint_container_summary(owner, detail, selection)
        return
    if runtime.hydrated_agent is not None and getattr(
        runtime.hydrated_agent, "identity", None
    ):
        # A previously hydrated agent for a different key must not stay visible.
        runtime.hydrated_agent = None
    header = archive_identity_header_from_light_row(selection.light_row, loading=True)
    if detail is None:
        return
    _paint_identity(detail, header)
    _show_titled(detail, ARCHIVE_LOADING_TITLE)


def _paint_container_summary(owner: Any, detail: Any, selection: Any) -> None:
    from ._archive_column import archive_container_members

    key = container_key_of(selection.archive_key) or ""
    members = archive_container_members(owner, key) if key else ()
    body = archive_container_summary_text(selection.light_row, members)
    if detail is None:
        return
    header = archive_identity_header_from_light_row(selection.light_row)
    _paint_identity(detail, header)
    show_cause = getattr(detail, "show_tab_empty_state", None)
    if callable(show_cause):
        show_cause("Container summary", body.plain)
    else:
        update = getattr(detail, "update", None)
        if callable(update):
            from ...widgets.decks.card_part import card_document, summary_card

            update(card_document(summary_card(body)))
        else:
            show_empty = getattr(detail, "show_empty", None)
            if callable(show_empty):
                show_empty()
    _paint_record_from_light_row(owner, detail, selection.light_row, members)


def arm_archive_detail_hydration(owner: Any) -> None:
    """Schedule pump-free hydration through the 150 ms detail debouncer."""
    remember_agents_detail_owner(owner)
    debouncer = getattr(owner, "_agent_detail_debouncer", None)
    schedule = getattr(debouncer, "schedule", None)
    if callable(schedule):
        schedule(lambda: _fire_archive_detail(owner))


def _fire_archive_detail(owner: Any) -> None:
    """Start hydration for the current Archive selection when still current."""
    if not scheduled_agents_detail_is_current(owner):
        return
    if not archive_detail_owns_panel(owner):
        return
    selection = get_agents_tab_selection(owner)
    if selection.row_kind == ARCHIVE_ROW_CONTAINER:
        detail = _detail_widget(owner)
        _paint_container_summary(owner, detail, selection)
        return
    if selection.row_kind != ARCHIVE_ROW_AGENT or not selection.archive_key:
        return
    generation = getattr(getattr(owner, "_agents_archive_view", None), "generation", 0)
    _spawn_reader_task(
        owner,
        _hydrate_archive_agent(
            owner,
            key=selection.archive_key,
            light_row=selection.light_row,
            generation=generation,
        ),
    )


def _spawn_reader_task(owner: Any, coro: Any) -> Any:
    spawner = getattr(owner, "_archive_spawn", None)
    if callable(spawner):
        task = spawner(
            owner,
            coro,
            name=_READER_TASK_NAME,
            registry_attr=_READER_TASK_REGISTRY,
        )
    else:
        task = spawn_pump_free_task(
            owner,
            coro,
            name=_READER_TASK_NAME,
            registry_attr=_READER_TASK_REGISTRY,
        )
    return task


def _archive_root(owner: Any) -> Path | None:
    """Return the injected test root or the process dismissed-bundles dir."""
    root = getattr(owner, "_archive_corpus_root", None)
    if root is not None:
        return root if isinstance(root, Path) else Path(str(root))
    try:
        from sase.ace.dismissed_agents import dismissed_bundles_dir

        return dismissed_bundles_dir()
    except Exception:
        return None


def _load_archive_bundle(
    owner: Any, light_row: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Disk work: resolve, load, stamp, and probe. Never writes."""
    from sase.ace.dismissed_agents_bundles import load_bundle_file

    path = resolve_archive_bundle_path(light_row, _archive_root(owner))
    if path is None:
        return {
            "unreadable": True,
            "path": None,
            "agent": None,
            "retained": (),
            "missing": (),
        }
    agent = load_bundle_file(path)
    if agent is None:
        return {
            "unreadable": True,
            "path": str(path),
            "agent": None,
            "retained": (),
            "missing": (),
        }
    mark_agent_archive_read_only(agent)
    retained, missing = probe_retained_archive_content(agent)
    return {
        "unreadable": False,
        "path": str(path),
        "agent": agent,
        "retained": retained,
        "missing": missing,
    }


def load_archive_bundle(
    owner: Any, light_row: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Public seam for Archive bundle hydration. Never writes.

    Split restore modules consume this instead of the private
    ``_load_archive_bundle`` so no module imports a ``_``-prefixed name
    across modules. Tests keep patching
    ``sase.ace.tui.actions.agents._archive_reader._load_archive_bundle``:
    this wrapper resolves that name at call time, so the patch still takes
    effect.
    """
    return _load_archive_bundle(owner, light_row)


def read_archive_bundle_json(
    owner: Any, light_row: Mapping[str, Any] | None = None
) -> str:
    """Return the on-disk Archive bundle JSON for ``light_row``.

    Callers must run this off the event loop. Resolves the selected Archive
    row when ``light_row`` is omitted. Raises ``FileNotFoundError`` when the
    bundle is missing.
    """
    row = light_row
    if row is None:
        try:
            from ._archive_column import archive_light_row
            from ._archive_view import agents_archive_view_state

            key = agents_archive_view_state(owner).archive.selected_key
            row = archive_light_row(owner, key)
        except Exception:
            row = None
    path = resolve_archive_bundle_path(row, _archive_root(owner))
    if path is None:
        raise FileNotFoundError("Archive bundle is not on disk")
    return path.read_text(encoding="utf-8")


async def _hydrate_archive_agent(
    owner: Any,
    *,
    key: str,
    light_row: Mapping[str, Any] | None,
    generation: int,
) -> None:
    runner = getattr(owner, "_archive_run_off_thread", None)
    if callable(runner):
        result = await runner(lambda: _load_archive_bundle(owner, light_row))
    else:
        result = await asyncio.to_thread(_load_archive_bundle, owner, light_row)
    if not _hydration_is_current(owner, key, generation):
        return
    _apply_hydration_result(owner, key, light_row, generation, result)


def _hydration_is_current(owner: Any, key: str, generation: int) -> bool:
    if not archive_detail_owns_panel(owner):
        return False
    state = getattr(owner, "_agents_archive_view", None)
    if state is None or int(getattr(state, "generation", -1)) != generation:
        return False
    archive = getattr(state, "archive", None)
    if getattr(archive, "selected_key", None) != key:
        return False
    # ``K`` focuses the pulse without moving the cursor: drop the hydration.
    if getattr(archive, "focused_section", ARCHIVE_SECTION_LIST) != (
        ARCHIVE_SECTION_LIST
    ):
        return False
    return True


def _apply_hydration_result(
    owner: Any,
    key: str,
    light_row: Mapping[str, Any] | None,
    generation: int,
    result: Mapping[str, Any],
) -> None:
    if not _hydration_is_current(owner, key, generation):
        return
    runtime = _reader_runtime(owner)
    runtime.archive_key = key
    runtime.generation = generation
    runtime.loading = False
    runtime.light_row = light_row
    runtime.bundle_path = result.get("path")
    runtime.retained = tuple(result.get("retained") or ())
    runtime.missing = tuple(result.get("missing") or ())
    unreadable = bool(result.get("unreadable"))
    runtime.unreadable = unreadable
    agent = result.get("agent")
    if agent is not None:
        mark_agent_archive_read_only(agent)
    runtime.hydrated_agent = None if unreadable else agent
    detail = _detail_widget(owner)
    header = archive_identity_header_from_light_row(
        light_row,
        unreadable=unreadable,
        retained=runtime.retained,
        missing=runtime.missing,
    )
    if detail is None:
        return
    _paint_identity(detail, header)
    if unreadable or agent is None:
        _show_titled(detail, ARCHIVE_UNREADABLE_TITLE, _UNREADABLE_DETAIL)
        _paint_record_from_light_row(owner, detail, light_row)
        return
    update = getattr(detail, "update_display", None)
    if callable(update):
        update(agent)
        return
    _show_titled(detail, ARCHIVE_UNREADABLE_TITLE, _UNREADABLE_DETAIL)


__all__ = [
    "arm_archive_detail_hydration",
    "clear_archive_reader_runtime",
    "hydrated_archive_agent_for",
    "load_archive_bundle",
    "paint_archive_detail_placeholder",
    "read_archive_bundle_json",
]

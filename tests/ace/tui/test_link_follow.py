"""App-level ``$`` link-follow behavior."""

from __future__ import annotations

import asyncio
from threading import Event

from sase.ace.tui.actions import link_follow
from sase.ace.tui.modals.artifact_links_panel_modal import (
    ArtifactLinksPanelModal,
    ArtifactLinksPanelResult,
)
from sase.ace.tui.widgets.artifacts.entry_navigation import LinkRequestState
from sase.core.artifact_entry_target import ArtifactEntryTarget

from ._link_follow_helpers import (
    _Agent,
    _App,
    _DeferredPane,
    _Pane,
    _chip,
    _resolving_only,
)


def test_action_double_dollar_follows_first_link_and_records_origin() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.7"))
    app = _App(
        chips=(_chip("bead:sase-ug.7", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin, query="limit:40"),
            "beads": _Pane(targets=(target,)),
        },
    )

    app.action_follow_artifact_link()
    assert app._pending_link_prefix is True
    app.action_follow_artifact_link()

    assert app.current_tab == "artifacts"
    assert app.current_artifacts_pane_key == "beads"
    assert app._artifacts_entry_navigator("beads").selected_entry_target() == target
    assert app.artifacts_project_scope == "demo"
    assert len(app._link_trail) == 1
    assert app._link_trail[0].origin == origin


def test_follow_link_drops_head_slice_limit_before_missing_warning() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    pane = _Pane(
        targets=(origin,),
        selected=origin,
        query="kind:log limit:40",
        target_after_limit=target,
    )
    app = _App(
        chips=(_chip("file:hidden.txt", target),),
        panes={"files": pane},
    )

    app._follow_link_number(1)

    assert pane.applied_queries == [("kind:log limit:all", True)]
    assert pane.selected_entry_target() == target
    assert app.notifications == [
        ("Revealed file:hidden.txt — press ^ to restore your query", None)
    ]
    assert len(app._link_trail) == 1


def test_projected_group_opens_scoped_links_panel_without_trail() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("stitches", ("sase", "0123456789abcdef"))
    app = _App(
        chips=(
            _chip(
                "stitch:sase@0123456789abcdef",
                target,
                origin="projected",
                created_by="projection:stitch-bead",
            ),
            _chip(
                "stitch:sase@fedcba9876543210",
                target,
                origin="projected",
                created_by="projection:stitch-bead",
            ),
        ),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )

    app._follow_link_number(1)

    assert app.notifications == []
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, ArtifactLinksPanelModal)
    assert modal._subject_ref == "file:origin.txt"
    assert len(modal._chips) == 2
    assert modal._scoped_label == "2 stitches"
    assert app._link_trail == []


def test_zero_opens_links_panel_with_staleness_notice() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    app._link_index_errors = ("demo: bad aggregate",)
    app._link_index_loading = True

    app._open_artifact_links_panel()

    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, ArtifactLinksPanelModal)
    assert modal._subject_ref == "file:origin.txt"
    assert modal._staleness_notice == (
        "Link index refresh in progress; showing the previous index.\n"
        "Some project link indexes were skipped: demo: bad aggregate"
    )


def test_links_panel_follow_result_jumps_without_numbered_rail_item() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    chip = _chip("bead:sase-ug.9", target)
    app = _App(
        chips=(chip,),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(targets=(target,)),
        },
    )

    app._open_artifact_links_panel()
    callback = app.screen_callbacks[0]
    assert callable(callback)
    callback(ArtifactLinksPanelResult(action="follow", chip=chip))

    assert app.current_artifacts_pane_key == "beads"
    assert app._artifacts_entry_navigator("beads").selected_entry_target() == target
    assert len(app._link_trail) == 1


def test_links_panel_add_result_dispatches_existing_authoring_action() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )

    app._open_artifact_links_panel()
    callback = app.screen_callbacks[0]
    assert callable(callback)
    callback(ArtifactLinksPanelResult(action="add"))

    assert app.artifact_link_marked == 1


async def test_links_panel_remove_result_uses_existing_store_remove(
    monkeypatch,
) -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    chip = _chip(
        "bead:sase-ug.9",
        ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9")),
        relation="implements",
        label="implemented-by",
        this_is_source=False,
    )
    app = _App(
        chips=(chip,),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    calls: list[tuple[str, str, str]] = []
    app.link_refresh_event = Event()

    def remove(source_ref: str, target_ref: str, relation: str) -> dict[str, object]:
        calls.append((source_ref, target_ref, relation))
        return {"rows": [{"relation": relation}]}

    monkeypatch.setattr(link_follow, "remove_artifact_link", remove)
    monkeypatch.setattr(link_follow, "artifact_link_index_drift_notice", lambda: "")

    app._open_artifact_links_panel()
    callback = app.screen_callbacks[0]
    assert callable(callback)
    callback(ArtifactLinksPanelResult(action="remove", chip=chip))
    assert await asyncio.wait_for(
        asyncio.to_thread(app.link_refresh_event.wait),
        timeout=1.0,
    )

    assert calls == [("bead:sase-ug.9", "file:origin.txt", "implements")]
    assert app.notifications == [
        (
            "removed 1 implements link @bead:sase-ug.9 -> @file:origin.txt",
            None,
        )
    ]
    assert app.active_artifacts_refreshes == 1
    assert app.link_index_refreshes == ["artifact_link_remove"]


def test_loaded_agent_link_prefers_agents_tab_over_artifacts_pane() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    artifact_target = ArtifactEntryTarget("agents", ("builder",))
    agent = _Agent(agent_name="builder", identity=("done", "builder", None))
    app = _App(
        chips=(_chip("agent:builder", artifact_target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "agents": _Pane(targets=()),
        },
        agents=(agent,),
    )

    app._follow_link_number(1)

    assert app.current_tab == "agents"
    assert app.current_idx == 0
    assert app._agents_last_identity == agent.identity
    assert app.refreshed == 1
    assert app.rail_refreshed == 1
    assert len(app._link_trail) == 1


def test_follow_link_resolves_epic_kind_mismatch_via_pane_resolver() -> None:
    """A bead ref's chip hint always synthesizes kind ``task`` (Class A)."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    wrong_kind_hint = ArtifactEntryTarget("beads", ("demo", "task", "sase-w3"))
    real_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-w3"))
    app = _App(
        chips=(_chip("bead:sase-w3", wrong_kind_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("bead", "sase-w3"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("beads")
    assert pane.selected_entry_target() == real_target
    assert len(app._link_trail) == 1


def test_follow_link_resolves_proposed_plan_kind_mismatch_via_pane_resolver() -> None:
    """A plan ref's chip hint always synthesizes stage ``archive`` (Class A)."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    wrong_stage_hint = ArtifactEntryTarget(
        "ref:plan", ("demo", "archive", "202609/x.md")
    )
    real_target = ArtifactEntryTarget("ref:plan", ("demo", "proposal", "notif-1"))
    app = _App(
        chips=(_chip("plan:202609/x.md", wrong_stage_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "ref:plan": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("plan", "202609/x.md"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("ref:plan")
    assert pane.selected_entry_target() == real_target


def test_follow_link_resolves_abbreviated_stitch_sha_via_pane_resolver() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    abbreviated_hint = ArtifactEntryTarget("stitches", ("sase", "abc1234"))
    real_target = ArtifactEntryTarget("stitches", ("sase", "abc1234567890"))
    app = _App(
        chips=(_chip("stitch:sase@abc1234", abbreviated_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "stitches": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("stitch", "sase@abc1234"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("stitches")
    assert pane.selected_entry_target() == real_target


def test_follow_link_resolves_cross_project_patch_via_pane_resolver() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    unscoped_hint = ArtifactEntryTarget("patches", ("", "shared-name"))
    real_target = ArtifactEntryTarget("patches", ("beta", "shared-name"))
    app = _App(
        chips=(_chip("patch:shared-name", unscoped_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "patches": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("patch", "shared-name"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("patches")
    assert pane.selected_entry_target() == real_target


def test_follow_link_uses_chip_target_hint_when_pane_resolver_has_no_answer() -> None:
    """A pane with no answer degrades to the old chip-hint behavior, not a miss."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.7"))
    app = _App(
        chips=(_chip("bead:sase-ug.7", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(targets=(target,)),  # no resolver configured
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("beads")
    assert pane.selected_entry_target() == target


def test_follow_link_no_longer_falls_back_to_family_reveal_rung() -> None:
    """The FAMILY-role reveal rung is gone; a miss reports honestly instead."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(targets=()),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("beads")
    assert pane.revealed is None
    assert app.notifications == [
        ("Bead has no bead:sase-ug.9 in its inventory", "warning")
    ]
    assert app._link_trail == []


def test_follow_into_deferred_pane_returns_pending_until_resolved() -> None:
    """A follow into a loading pane opens a transaction instead of failing."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)

    assert app._link_trail == []
    assert app.notifications == []
    assert app.rail_refreshed == 0
    assert beads_pane._pending_target == target
    assert app._link_follow_transaction is not None

    beads_pane.resolve(LinkRequestState.SELECTED, reveal=target)

    assert beads_pane.selected_entry_target() == target
    assert len(app._link_trail) == 1
    assert app._link_trail[0].origin == origin
    assert app.rail_refreshed == 1
    assert app._link_follow_transaction is None


def test_second_follow_supersedes_pending_and_ignores_stale_resolution() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    first_target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.1"))
    second_target = ArtifactEntryTarget("files", ("other.txt",))
    app = _App(
        chips=(
            _chip("bead:sase-ug.1", first_target),
            _chip("file:other.txt", second_target),
        ),
        panes={"files": _Pane(targets=(origin, second_target), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)
    first_generation = app._link_follow_transaction.generation
    assert beads_pane._pending_target == first_target

    app._follow_link_number(2)

    assert app.current_artifacts_pane_key == "files"
    assert app._artifacts_entry_navigator("files").selected_entry_target() == (
        second_target
    )
    assert len(app._link_trail) == 1
    assert app.rail_refreshed == 1
    assert app._link_follow_transaction is None

    # The superseded first request's later resolution is silently ignored:
    # no stale trail hop, no toast.
    app._complete_link_follow_request(first_generation, LinkRequestState.SELECTED)

    assert len(app._link_trail) == 1
    assert app.notifications == []


def test_pending_follow_resolves_to_authoritative_missing_after_limit_drop() -> None:
    """A later authoritative MISSING still tries the host fallback once."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)
    assert app.notifications == []

    beads_pane.resolve(LinkRequestState.MISSING)

    assert app.notifications == [
        ("Bead has no bead:sase-ug.9 in its inventory", "warning")
    ]
    assert app._link_trail == []
    assert app._link_follow_transaction is None


def test_pending_follow_resolves_to_failed_with_distinct_error_copy() -> None:
    """A load/query failure is never described as deletion or absence."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)
    beads_pane.resolve(LinkRequestState.FAILED)

    assert app.notifications == [("Failed to load Bead for bead:sase-ug.9", "error")]
    assert app._link_trail == []
    assert app._link_follow_transaction is None


def test_pane_is_loading_recognizes_stitches_collection_and_query_state() -> None:
    """Stitches collection/query-session in-flight work counts as loading."""

    class _RunningWorker:
        is_running = True

    class _StitchesPane:
        _collection_worker: object | None = None
        _query_result_pending = False

    pane = _StitchesPane()
    assert link_follow.pane_is_loading(pane) is False

    pane._collection_worker = _RunningWorker()
    assert link_follow.pane_is_loading(pane) is True

    pane._collection_worker = None
    pane._query_result_pending = True
    assert link_follow.pane_is_loading(pane) is True

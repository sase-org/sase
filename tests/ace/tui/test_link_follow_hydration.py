"""Targeted-hydration behavior for ``$`` link-follow."""

from __future__ import annotations

import asyncio
from threading import Event

from sase.ace.tui.widgets.artifacts.entry_navigation import (
    HydrationOutcome,
    HydrationResult,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget

from ._link_follow_helpers import _App, _Pane, _chip


async def _await_hydration(app: _App) -> None:
    """Drain every pump-free hydration task the app has spawned."""
    tasks = tuple(getattr(app, "_link_hydration_tasks", ()))
    if tasks:
        await asyncio.gather(*tasks)


async def _await_hydration_started(started: Event) -> None:
    """Wait until the blocked hydrate lookup has entered its worker thread."""
    entered = await asyncio.to_thread(started.wait, 2)
    if not entered:
        raise TimeoutError("hydration lookup did not start")


def test_hydration_not_attempted_when_a_reveal_rung_succeeds() -> None:
    """Fold expansion satisfies the follow, so hydration never fires."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    beads_pane = _Pane(targets=(), foldable=True)
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)

    assert beads_pane.selected_entry_target() == target
    assert beads_pane.hydrate_calls == []


async def test_hydration_fires_after_ladder_exhaustion_and_installs_row() -> None:
    """Every rung misses, so hydration resolves and finalizes the follow."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    hydrated_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-ug.9"))

    def hydrate(kind: str, payload: str) -> HydrationResult:
        assert (kind, payload) == ("bead", "sase-ug.9")
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(
        targets=(),
        hydrate_fn=hydrate,
        install_fn=lambda payload: hydrated_target,
    )
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert beads_pane.hydrate_calls == [("bead", "sase-ug.9")]
    assert beads_pane.installed_payloads == ["fetched-row"]
    assert beads_pane.selected_entry_target() == hydrated_target
    assert app.notifications == []
    # The row was reachable without any query rewrite once installed, so
    # no reveal rung ever touched the pane's host-limit query.
    assert beads_pane.applied_queries == []
    assert len(app._link_trail) == 1
    assert app.rail_refreshed == 1
    assert app._link_follow_transaction is None


async def test_slow_hydration_stays_pending_without_a_miss_toast() -> None:
    """A slow lookup keeps the transaction open instead of reporting absence."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    hydrated_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-ug.9"))
    started = Event()
    release = Event()

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        started.set()
        release.wait(timeout=2)
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(
        targets=(),
        hydrate_fn=hydrate,
        install_fn=lambda payload: hydrated_target,
    )
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration_started(started)

    assert app.notifications == []
    assert app._link_follow_transaction is not None
    assert app._link_trail == []

    release.set()
    await _await_hydration(app)

    assert beads_pane.selected_entry_target() == hydrated_target
    assert app.notifications == []
    assert len(app._link_trail) == 1


async def test_duplicate_hydration_requests_coalesce_into_one_lookup() -> None:
    """A repeated follow for the same pending ref reuses the in-flight lookup."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    hydrated_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-ug.9"))
    started = Event()
    release = Event()
    calls: list[tuple[str, str]] = []

    def hydrate(kind: str, payload: str) -> HydrationResult:
        calls.append((kind, payload))
        started.set()
        release.wait(timeout=2)
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(
        targets=(),
        hydrate_fn=hydrate,
        install_fn=lambda payload: hydrated_target,
    )
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration_started(started)
    first_generation = app._link_follow_transaction.generation

    # A second follow of the identical ref while the lookup is in flight
    # must not spawn a second blocking call.
    app._follow_link_number(1)
    second_generation = app._link_follow_transaction.generation

    assert calls == [("bead", "sase-ug.9")]
    assert second_generation != first_generation

    release.set()
    await _await_hydration(app)

    assert beads_pane.selected_entry_target() == hydrated_target
    assert len(app._link_trail) == 1


async def test_second_follow_supersedes_in_flight_hydration() -> None:
    """A follow into a different target while hydrating drops the stale result."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    first_target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    second_target = ArtifactEntryTarget("files", ("other.txt",))
    started = Event()
    release = Event()

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        started.set()
        release.wait(timeout=2)
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(targets=(), hydrate_fn=hydrate, install_fn=lambda payload: None)
    files_pane = _Pane(targets=(origin, second_target), selected=origin)
    app = _App(
        chips=(
            _chip("bead:sase-ug.9", first_target),
            _chip("file:other.txt", second_target),
        ),
        panes={"files": files_pane, "beads": beads_pane},
    )

    app._follow_link_number(1)
    await _await_hydration_started(started)

    app._follow_link_number(2)

    assert app._artifacts_entry_navigator("files").selected_entry_target() == (
        second_target
    )
    assert len(app._link_trail) == 1

    release.set()
    await _await_hydration(app)

    # The superseded hydration's late FETCHED result must not install a
    # row, record a trail hop, or emit a toast.
    assert beads_pane.installed_payloads == []
    assert len(app._link_trail) == 1
    assert app.notifications == []


async def test_hydration_exception_maps_to_failed() -> None:
    """An exception from the resolver is reported as FAILED, not deletion."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        raise RuntimeError("store unavailable")

    beads_pane = _Pane(targets=(), hydrate_fn=hydrate)
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert app.notifications == [("Failed to load Bead for bead:sase-ug.9", "error")]
    assert app._link_trail == []
    assert app._link_follow_transaction is None


async def test_hydration_absent_maps_to_dangling_message() -> None:
    """An authoritative direct-lookup miss reads as dangling, not inventory-miss."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        return HydrationResult(HydrationOutcome.ABSENT)

    beads_pane = _Pane(targets=(), hydrate_fn=hydrate)
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert app.notifications == [("No such artifact: bead:sase-ug.9", "warning")]
    assert app._link_trail == []


async def test_hydration_unsupported_falls_back_to_inventory_miss() -> None:
    """A pane with no direct source keeps the pre-hydration miss toast."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    beads_pane = _Pane(targets=())  # no hydrate_fn: defaults to UNSUPPORTED
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert beads_pane.hydrate_calls == [("bead", "sase-ug.9")]
    assert app.notifications == [
        ("Bead has no bead:sase-ug.9 in its inventory", "warning")
    ]


def test_dangling_ref_never_attempts_hydration() -> None:
    """A parsed-but-unroutable ref fails fast without ever reaching a pane."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    beads_pane = _Pane(targets=())
    app = _App(
        chips=(_chip("bug:missing", None),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)

    assert beads_pane.hydrate_calls == []
    assert app.notifications == [("No such artifact: bug:missing", "warning")]

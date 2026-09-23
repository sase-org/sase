"""Seam guarantees for ``$`` link-follow: no lost reports, no loading-as-absence.

Covers the ``seam`` phase: the host dispatch slot, the pane sync-report
contract, truthful fold handling, waiting on loading panes, post-load
re-resolution, project-scope handling, hydrated-row re-indexing, and the
user's closed-phase scenario against a real Beads pane.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.link_follow import (
    LinkTrailHop,
    _link_follow_outcomes,
)
from sase.ace.tui.widgets.artifacts import (
    agents_pane,
    beads_pane,
    files_pane,
    plans_pane,
)
from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.bead_filter_bar import BeadFilterBar
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import LinkRequestState
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.core.artifact_entry_target import ArtifactEntryTarget
from tests._agent_catalog_helpers import make_agent_catalog_row
from tests.ace.tui._artifacts_beads_helpers import snapshot as beads_snapshot
from tests.ace.tui._artifacts_files_helpers import (
    artifact_file,
    logical_file,
    snapshot as files_snapshot,
)
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot as plans_snapshot
from tests.ace.tui._link_follow_helpers import (
    _App,
    _DeferredPane,
    _Pane,
    _chip,
)


class _SyncReportingPane(_Pane):
    """Report synchronously, then return ``PENDING`` like the old panes did.

    Mirrors the confirmed root cause: Beads/Plans/Agents/Files resolved a
    cached request inline through ``_complete_entry_request`` but still
    returned ``PENDING``. The host dispatch slot must upgrade that return.
    """

    def request_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        reporter = getattr(self.app, "_complete_link_follow_request", None)
        assert callable(reporter)
        if self.select_entry_target(target):
            reporter(generation, LinkRequestState.SELECTED)
            return LinkRequestState.PENDING
        reporter(generation, LinkRequestState.MISSING)
        return LinkRequestState.PENDING


def test_sync_selected_report_survives_pending_return() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-9"))
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    pane = _SyncReportingPane(targets=(target,))
    app = _App(
        chips=(_chip("bead:sase-9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": pane,
        },
    )

    app._follow_link_number(1)

    assert pane.selected_entry_target() == target
    assert app._link_follow_transaction is None
    assert len(app._link_trail) == 1
    assert _link_follow_outcomes["select"] == 1


def test_sync_missing_report_survives_pending_return() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-9"))
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    pane = _SyncReportingPane(targets=())
    app = _App(
        chips=(_chip("bead:sase-9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": pane,
        },
    )

    app._follow_link_number(1)

    assert app._link_follow_transaction is None
    assert any(
        "has no bead:sase-9" in message for message, _severity in app.notifications
    )


def test_missing_while_loading_rerequests_without_toast() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-9"))
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    app = _App(
        chips=(_chip("bead:sase-9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    pane = _DeferredPane(app=app, targets=())
    app._panes["beads"] = pane
    pane._loading = True

    app._follow_link_number(1)
    assert app._link_follow_transaction is not None

    pane.resolve(LinkRequestState.MISSING)

    transaction = app._link_follow_transaction
    assert transaction is not None
    assert transaction.load_rerequested is True
    assert app.notifications == []

    pane._loading = False
    pane.resolve(LinkRequestState.SELECTED)

    assert app._link_follow_transaction is None
    assert len(app._link_trail) == 1


def test_second_missing_while_loading_does_not_loop() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-9"))
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    app = _App(
        chips=(_chip("bead:sase-9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    pane = _DeferredPane(app=app, targets=())
    app._panes["beads"] = pane
    pane._loading = True

    app._follow_link_number(1)
    pane.resolve(LinkRequestState.MISSING)
    assert app._link_follow_transaction is not None

    pane.resolve(LinkRequestState.MISSING)

    assert app._link_follow_transaction is not None
    assert app.notifications == []


def test_missing_reresolves_stale_chip_target_after_load() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    stale = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1.1"))
    phase = ArtifactEntryTarget("beads", ("alpha", "phase", "alpha-1.1"))
    loaded = {"on": False}

    def resolver(kind: str, payload: str) -> ArtifactEntryTarget | None:
        if loaded["on"] and (kind, payload) == ("bead", "alpha-1.1"):
            return phase
        return None

    pane = _Pane(targets=(phase,), resolver=resolver)
    app = _App(
        chips=(_chip("bead:alpha-1.1", stale),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": pane,
        },
    )
    app.current_tab = "artifacts"
    app.current_artifacts_pane_key = "beads"
    hop = LinkTrailHop(
        tab="artifacts", pane_key="beads", origin=origin, query_source=""
    )
    app._begin_link_follow_transaction("bead:alpha-1.1", stale, hop)
    app._link_trail_guard = False
    loaded["on"] = True

    app._handle_missing_link_follow(app._link_follow_transaction)

    assert pane.selected_entry_target() == phase
    assert app._link_follow_transaction is None
    assert len(app._link_trail) == 1


def test_specific_scope_switches_to_target_project() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-9"))
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    app = _App(
        chips=(_chip("bead:sase-9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    pane = _DeferredPane(app=app, targets=())
    app._panes["beads"] = pane
    app.artifacts_project_scope = "other"
    pane.entry_target_project = lambda _target: "demo"  # type: ignore[attr-defined]

    app._follow_link_number(1)

    assert app.artifacts_project_scope == "demo"
    transaction = app._link_follow_transaction
    assert transaction is not None
    assert transaction.scope_change == ("other", "demo")


def test_unknown_project_widens_to_all_when_unresolvable() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-9"))
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    app = _App(
        chips=(_chip("bead:sase-9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    pane = _DeferredPane(app=app, targets=())
    app._panes["beads"] = pane
    app.artifacts_project_scope = "alpha"

    app._follow_link_number(1)

    assert app.artifacts_project_scope is None
    transaction = app._link_follow_transaction
    assert transaction is not None
    assert transaction.scope_change == ("alpha", None)


class _ResolvingDeferred(_DeferredPane):
    def __init__(self, *, app: _App, resolved: ArtifactEntryTarget) -> None:
        super().__init__(app=app, targets=())
        self._resolved = resolved

    def entry_target_for_ref(
        self, kind: str, payload: str
    ) -> ArtifactEntryTarget | None:
        del kind, payload
        return self._resolved


def test_unknown_project_keeps_scope_when_resolvable() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-9"))
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    app = _App(
        chips=(_chip("bead:sase-9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    pane = _ResolvingDeferred(app=app, resolved=target)
    app._panes["beads"] = pane
    app.artifacts_project_scope = "alpha"

    app._follow_link_number(1)

    assert app.artifacts_project_scope == "alpha"
    transaction = app._link_follow_transaction
    assert transaction is not None
    assert transaction.scope_change is None


async def test_closed_phase_follow_selects_without_hanging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda project, **_kwargs: beads_snapshot(tmp_path, project=project),
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        pane.set_project_scope("alpha")
        await page.wait_for(
            lambda _state: (
                pane.snapshot is not None and pane.snapshot.project == "alpha"
            )
        )
        bar = pane.query_one(BeadFilterBar)
        display = bar.query_one("#bead-filter-display", Static)

        await page.press("/")
        bar.set_query("-status:closed limit:100")
        bar.post_message(BeadFilterBar.Submitted("-status:closed limit:100"))
        await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]
        await page.wait_for(lambda _state: "-status:closed" in display.render().plain)

        app = page.app
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1.1"))
        app._follow_artifacts_target("bead:alpha-1.1", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        assert pane.selected_entry_target() == ArtifactEntryTarget(
            "beads", ("alpha", "phase", "alpha-1.1")
        )


async def test_beads_sync_reports_visible_and_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = beads_snapshot(tmp_path, project="alpha")
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        pane.set_project_scope("alpha")
        await page.wait_for(lambda _state: pane.snapshot is value)

        visible = ArtifactEntryTarget("beads", ("alpha", "epic", "alpha-1"))
        assert pane.request_entry_target(visible, generation=None) is (
            LinkRequestState.SELECTED
        )
        assert pane.selected_entry_target() == visible

        missing = ArtifactEntryTarget("beads", ("alpha", "task", "no-such-bead"))
        assert pane.request_entry_target(missing, generation=None) is (
            LinkRequestState.MISSING
        )


async def test_files_sync_reports_visible_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (artifact_file("one"), artifact_file("two"))
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: files_snapshot(rows, project=project),
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"))
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)

        visible = ArtifactEntryTarget("files", (logical_file(rows[0]).logical_id,))
        assert pane.request_entry_target(visible, generation=None) is (
            LinkRequestState.SELECTED
        )
        assert pane.selected_entry_target() == visible

        missing = ArtifactEntryTarget("files", ("no-such-file.txt",))
        assert pane.request_entry_target(missing, generation=None) is (
            LinkRequestState.MISSING
        )


async def test_agents_sync_reports_visible_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        make_agent_catalog_row("alpha.1", project="alpha"),
        make_agent_catalog_row("alpha.2", project="alpha"),
    )

    def load(project: str | None, limit: int | None = None) -> AgentsSnapshot:
        return AgentsSnapshot(
            project=project,
            rows=rows,
            total_row_count=len(rows),
            complete=True,
        )

    monkeypatch.setattr(agents_pane, "load_agents_snapshot", load)

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("agents"))
        pane = page.query_one_widget("#artifacts-agents-pane", ArtifactsAgentsPane)
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.complete
        )

        visible = ArtifactEntryTarget("agents", ("alpha.1",))
        assert pane.request_entry_target(visible, generation=None) is (
            LinkRequestState.SELECTED
        )
        assert pane.selected_entry_target() == visible

        missing = ArtifactEntryTarget("agents", ("no-such-agent",))
        assert pane.request_entry_target(missing, generation=None) is (
            LinkRequestState.MISSING
        )


async def test_plans_sync_reports_visible_and_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = plans_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane,
        "load_plans_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        pane.set_project_scope("alpha")
        await page.wait_for(
            lambda _state: (
                pane.snapshot is value and pane.snapshot.project == pane.project_scope
            )
        )

        visible = ArtifactEntryTarget("ref:plan", ("alpha", "proposal", "proposal-1"))
        assert pane.request_entry_target(visible, generation=None) is (
            LinkRequestState.SELECTED
        )
        assert pane.selected_entry_target() == visible

        missing = ArtifactEntryTarget("ref:plan", ("alpha", "archive", "nope.md"))
        assert pane.request_entry_target(missing, generation=None) is (
            LinkRequestState.MISSING
        )


async def test_beads_hydrated_row_becomes_queryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.model import Issue, IssueType

    value = beads_snapshot(tmp_path, project="alpha")
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        pane.set_project_scope("alpha")
        await page.wait_for(lambda _state: pane.snapshot is value)
        before = len(pane._query_index)

        issue = Issue(
            id="alpha-hydrated",
            title="Hydrated follow-up",
            issue_type=IssueType.TASK,
        )
        target = pane.install_hydrated_row(("alpha", issue, None))

        assert target == ArtifactEntryTarget(
            "beads", ("alpha", "task", "alpha-hydrated")
        )
        assert len(pane._query_index) == before + 1
        assert pane.host_query_row_for_target(target) is not None


async def test_plans_hydrated_row_becomes_queryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.plan_search.model import Plan, PlanSearchMatch

    value = plans_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane,
        "load_plans_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        pane.set_project_scope("alpha")
        await page.wait_for(
            lambda _state: (
                pane.snapshot is value and pane.snapshot.project == pane.project_scope
            )
        )
        before = len(pane._query_index)

        archived_path = tmp_path / "202607" / "hydrated.md"
        match = PlanSearchMatch(
            plan=Plan(
                source="repo",
                kind="epic",
                path=str(archived_path),
                relpath="202607/hydrated.md",
                name="hydrated",
                title="Hydrated rollout",
                status="done",
                created_at="2026-07-04 10:00:00",
                prompt_link="",
                summary="Hydrated summary.",
                body="Hydrated body.",
                frontmatter={"tier": "epic", "status": "done"},
            ),
            matched_fields=[],
            score=1.0,
        )
        target = pane.install_hydrated_row(("alpha", "plans", match))

        assert target is not None
        assert len(pane._query_index) == before + 1
        assert pane.host_query_row_for_target(target) is not None


async def test_agents_hydrated_row_rebuilds_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (make_agent_catalog_row("alpha.1", project="alpha"),)

    def load(project: str | None, limit: int | None = None) -> AgentsSnapshot:
        return AgentsSnapshot(
            project=project,
            rows=rows,
            total_row_count=len(rows),
            complete=True,
        )

    monkeypatch.setattr(agents_pane, "load_agents_snapshot", load)

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("agents"))
        pane = page.query_one_widget("#artifacts-agents-pane", ArtifactsAgentsPane)
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.complete
        )

        fetched = make_agent_catalog_row("hydrated-agent", project="alpha")
        target = pane.install_hydrated_row(fetched)

        assert target == ArtifactEntryTarget("agents", ("hydrated-agent",))
        await page.wait_for(
            lambda _state: (
                pane._query_index is not None
                and any(
                    "hydrated-agent" in row_id for row_id in pane._query_index.row_ids
                )
            )
        )


async def test_files_hydrated_row_becomes_queryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (artifact_file("one"),)
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: files_snapshot(rows, project=project),
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"))
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        before = len(pane._query_index)

        hydrated = logical_file(artifact_file("hydrated"))
        target = pane.install_hydrated_row(hydrated)

        assert target is not None
        assert len(pane._query_index) == before + 1

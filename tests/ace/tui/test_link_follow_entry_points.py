"""Entry-points: one engine for every jump, plus the end-to-end matrix."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.artifacts.entry_navigation import LinkRequestState
from sase.ace.tui.widgets.bgcmd_list import ChopItem
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationKeymap, RelationRole
from tests.ace.tui._link_follow_helpers import _App, _Pane, _chip


class _RelationApp(TreeNavigationMixin):
    """Minimal relation-navigation host with an engine spy."""

    def __init__(self, *, pane, contract_id: str = "beads") -> None:
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Contract:
            id: str

            def has(self, capability) -> bool:  # noqa: ANN001, ANN202
                return True

        self.current_tab = "artifacts"
        self.current_artifacts_pane_key = contract_id
        self.active_artifacts_contract = _Contract(contract_id)
        self._relation_keymap = RelationKeymap()
        self._ancestor_mode_active = False
        self._child_mode_active = False
        self._sibling_mode_active = False
        self._child_key_buffer = ""
        self._pane = pane
        self.follow_calls: list[tuple[str, ArtifactEntryTarget, object]] = []
        self.synced = 0

    def _artifacts_entry_navigator(self, pane_key=None):  # noqa: ANN001, ANN202
        return self._pane

    def _request_artifacts_entry(self, target, *, generation=None):  # noqa: ANN001, ANN202
        del generation
        if self._pane.select_entry_target(target):
            return LinkRequestState.SELECTED
        return LinkRequestState.MISSING

    def _sync_active_artifacts_entry_state(self) -> None:
        self.synced += 1

    def _current_link_trail_origin(self):  # noqa: ANN202
        from sase.ace.tui.actions._link_follow_types import LinkTrailHop

        return LinkTrailHop(
            tab="artifacts",
            pane_key="beads",
            origin=self._pane.selected_entry_target(),
            query_source="limit:40",
            project_scope=None,
            axe_key=None,
        )

    def _follow_artifacts_target(self, ref, chip_target, origin, **kwargs):  # noqa: ANN001, ANN202
        self.follow_calls.append((ref, chip_target, origin))


class _RelationPane:
    def __init__(self, *, origin, select_ok: bool = True) -> None:
        self._origin = origin
        self._select_ok = select_ok
        self.current = origin
        self.recorded = None
        self.revealed = None

    def selected_entry_target(self):  # noqa: ANN202
        return self.current

    def record_relation_origin(self, origin) -> None:  # noqa: ANN001
        self.recorded = origin

    def select_entry_target(self, target) -> bool:  # noqa: ANN001
        if self._select_ok and target == self._origin:
            self.current = target
            return True
        return False

    def reveal_entry_target(self, target, *, role) -> bool:  # noqa: ANN001
        self.revealed = (target, role)
        return False


def test_relation_cross_pane_routes_through_engine() -> None:
    origin = ArtifactEntryTarget("beads", ("demo", "phase", "origin"))
    target = ArtifactEntryTarget("files", ("notes.md",))
    app = _RelationApp(pane=_RelationPane(origin=origin))
    app._navigate_to_relation_target(target, role=RelationRole.LINK)
    assert len(app.follow_calls) == 1
    ref, chip_target, _hop = app.follow_calls[0]
    assert ref == "file:notes.md"
    assert chip_target == target
    assert app._pane.recorded == origin


def test_relation_same_pane_miss_routes_through_engine() -> None:
    origin = ArtifactEntryTarget("beads", ("demo", "phase", "origin"))
    target = ArtifactEntryTarget("beads", ("demo", "phase", "hidden"))
    app = _RelationApp(
        pane=_RelationPane(origin=origin, select_ok=False),
    )
    app._navigate_to_relation_target(target, role=RelationRole.DESCENDANT)
    assert len(app.follow_calls) == 1
    ref, chip_target, _hop = app.follow_calls[0]
    assert ref == "bead:hidden"
    assert chip_target == target


def test_relation_patches_keeps_lens() -> None:
    origin = ArtifactEntryTarget("patches", ("demo", "base"))
    target = ArtifactEntryTarget("patches", ("demo", "other"))

    class _PatchPane(_RelationPane):
        def reveal_entry_target(self, target, *, role) -> bool:  # noqa: ANN001
            self.revealed = (target, role)
            return True

    pane = _PatchPane(origin=origin, select_ok=False)
    app = _RelationApp(pane=pane, contract_id="patches")
    app._navigate_to_relation_target(target, role=RelationRole.ANCESTOR)
    assert app.follow_calls == []
    assert pane.revealed == (target, RelationRole.ANCESTOR)


def _chop_app(*, items, snapshots=None) -> _App:
    app = _App(chips=(), panes={"files": _Pane(targets=(), selected=None)})
    app._axe_items = list(items)
    app._axe_chop_snapshots = dict(snapshots or {})
    app._axe_fold_manager = FoldStateManager()
    app._axe_last_idx = 0
    app._axe_last_item_key = None
    app.current_tab = "artifacts"
    app.current_idx = 0
    app._link_trail_forward = []  # type: ignore[attr-defined]
    app._link_trail_guard = False  # type: ignore[attr-defined]
    app._link_follow_agents_tab_filtered = False  # type: ignore[attr-defined]
    app._build_axe_items = lambda: None  # noqa: E731
    app._refresh_current_tab = lambda: None  # noqa: E731
    app.refresh_link_rail = lambda: None  # noqa: E731
    app._save_current_tab_position = lambda: setattr(app, "saved_positions", 1)  # noqa: E731
    return app


def test_chop_collapsed_scheduler_expands_and_selects() -> None:
    app = _chop_app(items=(ChopItem("lj", "chop"),))
    # Both folds start collapsed (default); the chop row is present in the
    # harness list to simulate a rebuilt item list.
    expanded: list[str] = []
    assert app._follow_chop_link("lj/chop", expanded=expanded) is True
    assert expanded == ["lj"]
    assert app._axe_fold_manager.get("lumberjack:lj").name != "COLLAPSED"
    assert app._axe_fold_manager.get("service:scheduler").name != "COLLAPSED"
    assert app.current_tab == "services"
    assert app.current_idx == 0


def test_chop_failure_undoes_expansions() -> None:
    app = _chop_app(items=())
    expanded: list[str] = []
    assert app._follow_chop_link("lj/missing", expanded=expanded) is False
    # The caller discards `expanded` on failure; the folds themselves roll back.
    assert app._axe_fold_manager.get("lumberjack:lj").name == "COLLAPSED"
    assert app._axe_fold_manager.get("service:scheduler").name == "COLLAPSED"
    assert app.notifications
    assert "job:lj/missing" in app.notifications[0][0]


def test_unconfigured_research_reports_without_landing_on_stitches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("ref:research", ("", "archive", "notes"))
    app = _App(
        chips=(_chip("research:notes", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifact_tabs.descriptor_for_artifacts_pane_id",
        lambda pane_id: None if pane_id == "ref:research" else object(),
    )
    app._follow_single_link_chip(app._chips[0])
    assert app.current_artifacts_pane_key != "stitches"
    assert app.current_artifacts_pane_key == "files"
    assert app.notifications
    title = app.notification_details[0][2]
    message = app.notification_details[0][0]
    assert title.startswith("Cannot follow")
    assert "not configured" in message


def test_dangling_ref_reports_without_trail() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    app = _App(
        chips=(_chip("bead:missing", None),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    # An unresolvable chip target with no pane answer stays dangling.
    app._follow_single_link_chip(app._chips[0])
    assert app._link_trail == []
    assert app.notifications


# --- Links-panel-driven end-to-end matrix (AcePage, real panes) ---


async def _open_beads_matrix(page, tmp_path: Path, monkeypatch) -> object:
    from sase.ace.tui.widgets.artifacts import beads_pane
    from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
    from tests.ace.tui._artifacts_beads_helpers import snapshot as beads_snapshot

    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda project, **_kwargs: beads_snapshot(tmp_path, project=project),
    )
    await page.press(page.artifacts_digit("beads"))
    pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
    pane.set_project_scope("alpha")
    await page.wait_for(
        lambda _state: pane.snapshot is not None and pane.snapshot.project == "alpha"
    )
    return pane


async def _set_beads_query(page, pane, query: str) -> None:
    from textual.widgets import Static

    from sase.ace.tui.widgets.artifacts.bead_filter_bar import BeadFilterBar

    bar = pane.query_one(BeadFilterBar)
    display = bar.query_one("#bead-filter-display", Static)
    await page.press("/")
    bar.set_query(query)
    bar.post_message(BeadFilterBar.Submitted(query))
    await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]
    await page.wait_for(lambda _state: query in display.render().plain)


async def _follow_chip(page, chip) -> None:
    app = page.app
    app._follow_single_link_chip(chip)
    await page.wait_for(lambda _state: app._link_follow_transaction is None)


async def test_matrix_closed_bead_phase_via_links_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closed phase via the Links-panel chip path lands in its epic family."""

    from sase.ace.testing import AcePage
    from sase.ace.tui.actions._link_follow_toast import format_reveal_toast
    from sase.ace.tui.actions.link_follow import _link_follow_outcomes

    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads_matrix(page, tmp_path, monkeypatch)
        await _set_beads_query(page, pane, "-status:closed limit:100")
        before = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-ready"))
        assert pane.select_entry_target(before)
        page.app._note_artifacts_selection_for_link_trail()

        chip_target = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1.1"))
        chip = _chip("bead:alpha-1.1", chip_target)
        origin_query = pane.host_limit_query()
        await _follow_chip(page, chip)

        app = page.app
        target = ArtifactEntryTarget("beads", ("alpha", "phase", "alpha-1.1"))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "id:alpha-1.* limit:100"
        assert _link_follow_outcomes["context"] >= 1
        assert len(app._link_trail) == 1

        reveal = app._link_reveals["beads"]
        assert reveal.origin.canonical == origin_query
        title, message = format_reveal_toast(
            app._build_reveal_outcome(
                _last_transaction_for_test(app),
                pane,
                pane.host_limit_query(),
                reveal,
            ),
            restore_key="^",
            back_key="ctrl+o",
            accent="cyan",
        )
        assert "alpha-1.1" in title
        assert "id:alpha-1.* limit:100" in message

        app.action_prev_query()
        await page.wait_for(
            lambda _state: pane.host_limit_query() == "-status:closed limit:100"
        )
        assert pane.selected_entry_target() == before

        # ctrl+o returns to the origin hop as well (trail still holds one hop
        # until ^ clears it; walk back explicitly from a fresh follow).
        await _follow_chip(page, chip)
        assert pane.selected_entry_target() == target
        assert app._walk_link_trail_back() is True
        await page.wait_for(
            lambda _state: pane.host_limit_query() == "-status:closed limit:100"
        )


def _last_transaction_for_test(app):  # noqa: ANN001, ANN202
    """Return a minimal transaction stub carrying the last follow's ref/target."""

    from sase.ace.tui.actions._link_follow_types import LinkFollowTransaction

    pane = app._artifacts_entry_navigator()
    target = pane.selected_entry_target() if pane is not None else None
    origin = (
        app._link_trail[-1] if app._link_trail else app._current_link_trail_origin()
    )
    reveal = app._link_reveals.get("beads") if hasattr(app, "_link_reveals") else None
    return LinkFollowTransaction(
        generation=app._link_follow_generation,
        ref="bead:alpha-1.1",
        target=target,
        origin=origin,
        rung=0,
        origin_query=getattr(reveal, "origin", None),
        origin_target=getattr(reveal, "origin_target", None),
        scope_change=None,
    )


async def test_matrix_closed_epic_via_links_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.testing import AcePage

    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads_matrix(page, tmp_path, monkeypatch)
        await _set_beads_query(page, pane, "id:alpha-open")
        chip = _chip(
            "bead:alpha-1",
            ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1")),
        )
        await _follow_chip(page, chip)
        target = ArtifactEntryTarget("beads", ("alpha", "epic", "alpha-1"))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "id:alpha-1 id:alpha-1.*"
        assert len(page.app._link_trail) == 1
        page.app.action_prev_query()
        await page.wait_for(lambda _state: pane.host_limit_query() == "id:alpha-open")


async def test_matrix_task_beyond_limit_via_links_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.testing import AcePage

    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads_matrix(page, tmp_path, monkeypatch)
        await _set_beads_query(page, pane, "limit:1")
        chip = _chip(
            "bead:alpha-open",
            ArtifactEntryTarget("beads", ("alpha", "task", "alpha-open")),
        )
        await _follow_chip(page, chip)
        target = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-open"))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "id:alpha-open limit:1"
        assert len(page.app._link_trail) == 1


async def test_matrix_agent_hood_via_links_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent hood context reached through the Links-panel chip entry point."""

    from sase.ace.testing import AcePage
    from sase.ace.tui.widgets.artifacts import agents_pane
    from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
    from tests.ace.tui.test_link_follow_flat_panes import _agent_rows, _load_agents

    async with AcePage(initial_tab="patches") as page:
        monkeypatch.setattr(
            agents_pane, "load_agents_snapshot", _load_agents(_agent_rows())
        )
        await page.press(page.artifacts_digit("agents"))
        pane = page.query_one_widget("#artifacts-agents-pane", ArtifactsAgentsPane)
        await page.wait_for(
            lambda _state: (
                pane.snapshot is not None
                and pane.snapshot.complete
                and pane._query_index is not None
            )
        )
        before = ArtifactEntryTarget("agents", ("other",))
        assert pane.select_entry_target(before)
        pane._commit_agents_query("name:other limit:100")
        await page.wait_for(
            lambda _state: (
                ArtifactEntryTarget("agents", ("atlas.1",)) not in pane.entry_targets()
            )
        )
        page.app._note_artifacts_selection_for_link_trail()
        rows = _agent_rows()
        _ = rows
        chip = _chip("agent:atlas.1", ArtifactEntryTarget("agents", ("atlas.1",)))
        # Drive the Artifacts engine directly: the Agents-tab path is covered
        # by flat-panes; the panel falls through here when the tab hides it.
        app = page.app
        origin = app._current_link_trail_origin()
        app._follow_artifacts_target("agent:atlas.1", chip.neighbor_target, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)
        assert pane.selected_entry_target() == ArtifactEntryTarget(
            "agents", ("atlas.1",)
        )
        assert pane.host_limit_query() == "name:atlas.* limit:100"
        assert len(app._link_trail) == 1
        app.action_prev_query()
        await page.wait_for(
            lambda _state: pane.host_limit_query() == "name:other limit:100"
        )


async def test_matrix_file_via_links_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.ace.testing import AcePage
    from sase.ace.tui.widgets.artifacts import files_pane
    from sase.ace.tui.widgets.artifacts.files_filtering import parse_files_filter_query
    from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
    from tests.ace.tui._artifacts_files_helpers import artifact_file, snapshot

    rows = (
        artifact_file("a", source_path="a.md", agent_name="atlas.1--code"),
        artifact_file("b", source_path="b.md", agent_name="atlas.1--code"),
        artifact_file("c", source_path="c.md", agent_name="other"),
    )
    async with AcePage(initial_tab="patches") as page:
        monkeypatch.setattr(
            files_pane,
            "load_files_snapshot",
            lambda project, _limit: snapshot(rows, project=project),
        )
        await page.press(page.artifacts_digit("files"))
        pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        before = ArtifactEntryTarget("files", ("c.md",))
        assert pane.select_entry_target(before)
        pane._commit_files_filter_values(parse_files_filter_query("agent:other"))
        target = ArtifactEntryTarget("files", ("a.md",))
        await page.wait_for(lambda _state: target not in pane.entry_targets())
        page.app._note_artifacts_selection_for_link_trail()
        chip = _chip("file:a.md", target)
        await _follow_chip(page, chip)
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "agent:atlas.1--code"
        assert len(page.app._link_trail) == 1
        page.app.action_prev_query()
        await page.wait_for(lambda _state: pane.host_limit_query() == "agent:other")


async def test_matrix_links_panel_key_path_follows_first_chip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real $0 panel path follows the chosen chip through the engine."""

    from sase.ace.testing import AcePage
    from sase.ace.tui.modals.artifact_links_panel_modal import (
        ArtifactLinksPanelModal,
    )

    async with AcePage(initial_tab="patches") as page:
        pane = await _open_beads_matrix(page, tmp_path, monkeypatch)
        await _set_beads_query(page, pane, "-status:closed limit:100")
        before = ArtifactEntryTarget("beads", ("alpha", "task", "alpha-ready"))
        assert pane.select_entry_target(before)
        page.app._note_artifacts_selection_for_link_trail()

        chip = _chip(
            "bead:alpha-1.1",
            ArtifactEntryTarget("beads", ("alpha", "task", "alpha-1.1")),
        )
        app = page.app
        app.link_edges_for_selection = lambda: (chip,)  # type: ignore[method-assign]
        # $0 arms the link prefix then opens the panel; call the $0 handler
        # directly to avoid filter-bar focus swallowing "$" in harness.
        app._open_artifact_links_panel()
        await page.wait_for(
            lambda _state: isinstance(app.screen, ArtifactLinksPanelModal)
        )
        await page.press("a")
        await page.wait_for(lambda _state: app._link_follow_transaction is None)
        assert pane.selected_entry_target() == ArtifactEntryTarget(
            "beads", ("alpha", "phase", "alpha-1.1")
        )
        assert pane.host_limit_query() == "id:alpha-1.* limit:100"


async def test_matrix_old_stitch_via_links_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stitch outside the window lands via the Links-panel chip path."""

    from datetime import UTC, datetime

    from sase.ace.testing import AcePage
    from tests.ace.tui.test_link_follow_bounded_panes import (
        _fake_provider,
        _old_commit,
        _open_stitches,
        _result,
        _set_stitches_query,
        _window_collector,
        OLD_SHA,
        REPO,
    )

    now = int(datetime.now(tz=UTC).timestamp())
    old_timestamp = now - 10 * 86400
    recent = _result(now)
    from dataclasses import replace

    full = replace(recent, commits=(*recent.commits, _old_commit(old_timestamp)))
    page, pane = await _open_stitches(
        monkeypatch, _window_collector(recent, full, old_timestamp)
    )
    try:
        await _set_stitches_query(
            page,
            pane,
            "sidecar:false since:24h",
            expect="sidecar:false merges:hide since:24h",
        )
        old = _old_commit(old_timestamp)
        _fake_provider(monkeypatch, "abc1234", old.commit, expect_cwd="/tmp/alpha")
        chip = _chip(
            f"stitch:{REPO}@abc1234",
            ArtifactEntryTarget("stitches", (REPO, "abc1234")),
        )
        app = page.app
        app._follow_single_link_chip(chip)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)
        assert pane.selected_entry_target() == ArtifactEntryTarget(
            "stitches", (REPO, OLD_SHA)
        )
        assert len(app._link_trail) == 1
        app.action_prev_query()
        await page.wait_for(
            lambda _state: (
                pane.host_limit_query() == "sidecar:false merges:hide since:24h"
            )
        )
    finally:
        await page.__aexit__(None, None, None)


async def test_matrix_archived_plan_via_links_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.testing import AcePage
    from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
    from sase.ace.tui.widgets.artifacts.plans_list import plan_row_target
    from tests.ace.tui.test_link_follow_bounded_panes import _open_plans

    async with AcePage(initial_tab="patches") as page:
        pane = await _open_plans(page, tmp_path, monkeypatch)
        archive_row = next(row for row in pane._rows.values() if row.kind == "archive")
        target = plan_row_target(archive_row)
        identity = target.parts[2]
        bar = pane.query_one(PlanFilterBar)
        bar.post_message(PlanFilterBar.Submitted("kind:active"))
        await page.wait_for(lambda _state: pane.host_limit_query() == "kind:active")
        chip = _chip(f"plan:{identity}", target)
        app = page.app
        app._follow_single_link_chip(chip)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == f"path:{identity}"
        assert len(app._link_trail) == 1
        app.action_prev_query()
        await page.wait_for(lambda _state: pane.host_limit_query() == "kind:active")


async def test_matrix_filtered_patch_via_links_panel() -> None:
    from sase.ace.testing import AcePage
    from sase.ace.testing.fixtures import make_patch
    from sase.ace.tui.widgets.artifacts.panes import ArtifactsPatchesPane
    from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target

    patches = [
        make_patch(
            name="stack-root",
            description="stack root",
            status="Ready",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="stack-mid",
            description="stack middle",
            status="Ready",
            parent="stack-root",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="stack-leaf",
            description="stack leaf",
            status="Ready",
            parent="stack-mid",
            file_path="/tmp/stack.sase",
        ),
        make_patch(
            name="unrelated",
            description="something else entirely",
            status="Ready",
            file_path="/tmp/stack.sase",
        ),
    ]
    async with AcePage(initial_tab="patches", patches=patches) as page:
        app = page.app
        await page.press(page.artifacts_digit("patches"))
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        leaf = next(item for item in patches if item.name == "stack-leaf")
        target = patch_row_target(leaf)
        app._commit_patch_query("unrelated")
        chip = _chip("patch:stack-leaf", target)
        app._follow_single_link_chip(chip)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "ancestor:stack-root"
        assert len(app._link_trail) == 1
        assert app._walk_link_trail_back() is True


def test_matrix_chop_via_links_panel_with_trail_and_back() -> None:
    """A collapsed-scheduler chop follows via the panel and walks back."""

    from sase.ace.tui.relations.link_index import LinkChip

    app = _chop_app(items=(ChopItem("lj", "chop"),))
    chip = LinkChip(
        relation="runs",
        label="runs",
        directed=True,
        this_is_source=True,
        neighbor_ref="job:lj/chop",
        neighbor_target=None,
        accent="#5FD7D7",
        icon="⚒",
        why="",
        origin="manual",
        uses=1,
        created_by="tester",
        created_at="2026-08-26T00:00:00Z",
        writable=False,
    )
    app._chips = (chip,)
    app._follow_single_link_chip(chip)
    assert app.current_tab == "services"
    assert len(app._link_trail) == 1
    hop = app._link_trail[0]
    assert hop.axe_fold_expanded == "lj"
    # ctrl+o collapses the lumberjack rung (scheduler stays expanded by design,
    # mirroring the pending-selection path).
    app.collapse_lumberjack_after_link_trail("lj")
    assert app._axe_fold_manager.get("lumberjack:lj").name == "COLLAPSED"

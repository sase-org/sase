"""Collapse/expand the Artifacts relation panel with ``.``."""

from __future__ import annotations

from dataclasses import replace as _replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.patch import Patch
from sase.ace.testing import AcePage
from sase.ace.testing.fixtures import make_patch
from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.commits import CommitsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.ace.tui.widgets.artifacts.files_data import FileVersion, LogicalFile
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.panes import ArtifactsPatchesPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.artifacts.relation_panel import (
    RelationPanel,
    _build_collapsed_rail,
)
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from sase.core.artifact_relation_layout import (
    RelationKeymap,
    RelationRole,
    build_relation_view,
)
from sase.core.artifact_relations import RelationEdge, build_relation_index
from sase.vcs_log.models import VcsLogResult
from tests.ace.tui._artifacts_beads_helpers import snapshot as beads_snapshot
from tests.ace.tui._artifacts_files_helpers import snapshot as files_snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests.ace.tui._artifacts_plans_helpers import _snapshot as plans_snapshot
from tests.ace.tui._commits_pane_helpers import _result as stitches_result
import sase.ace.tui.widgets.artifacts.commits as commits_module


def _plain(widget: Any) -> str:
    content = getattr(widget, "content", None)
    if content is None:
        content = getattr(widget, "_content", None)
    if content is None:
        render = getattr(widget, "render", None)
        content = render() if callable(render) else ""
    if hasattr(content, "plain"):
        return str(content.plain)
    return str(content or "")


def _decl(
    name: str,
    kind: RelationKind,
    *,
    inverse: str | None = None,
    label: str | None = None,
) -> PaneRelationDecl:
    return PaneRelationDecl(
        name=name,
        kind=kind,
        label=label or name.title(),
        source="test",
        target_pane=None,
        inverse=inverse,
        directed=kind is not RelationKind.FAMILY,
        transitive=kind is RelationKind.HIERARCHY,
    )


def _target(name: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="patches", parts=("demo", name))


def _edge(
    relation: str,
    source: ArtifactEntryTarget,
    target: ArtifactEntryTarget,
    *,
    kind: RelationKind = RelationKind.HIERARCHY,
) -> RelationEdge:
    return RelationEdge(
        kind=kind,
        relation=relation,
        label=relation.title(),
        source=source,
        target=target,
    )


def _relation_index() -> tuple[Any, ArtifactEntryTarget, tuple[PaneRelationDecl, ...]]:
    origin = _target("current")
    parent = _target("parent")
    child = _target("child")
    grandchild = _target("grandchild")
    sibling = _target("current__1")
    relations = (
        _decl(
            "ancestors", RelationKind.HIERARCHY, inverse="children", label="Ancestors"
        ),
        _decl(
            "children", RelationKind.HIERARCHY, inverse="ancestors", label="Children"
        ),
        _decl("siblings", RelationKind.FAMILY, label="Siblings"),
    )
    index = build_relation_index(
        pane_id="patches",
        relations=relations,
        edges=(
            _edge("ancestors", origin, parent),
            _edge("children", origin, child),
            _edge("children", child, grandchild),
            _edge("siblings", origin, sibling, kind=RelationKind.FAMILY),
        ),
        known_targets={origin, parent, child, grandchild, sibling},
    )
    return index, origin, relations


def test_collapsed_rail_is_one_line_with_declared_labels() -> None:
    index, origin, relations = _relation_index()
    view = build_relation_view(index=index, origin=origin, relations=relations)
    text = _build_collapsed_rail(
        view,
        accent="#87D7FF",
        mode_keys={
            RelationRole.ANCESTOR: "<",
            RelationRole.DESCENDANT: ">",
            RelationRole.FAMILY: "~",
        },
    )

    assert text is not None
    assert view.keymap.ancestors
    assert view.keymap.children
    assert "\n" not in text.plain
    assert "▸" in text.plain
    assert "< 1 ancestors" in text.plain
    assert "> 2 children" in text.plain
    assert "~ 1 siblings" in text.plain


def test_collapsed_rail_leads_with_expand_chip_and_verb() -> None:
    index, origin, relations = _relation_index()
    view = build_relation_view(index=index, origin=origin, relations=relations)
    text = _build_collapsed_rail(
        view,
        accent="#87D7FF",
        mode_keys={
            RelationRole.ANCESTOR: "<",
            RelationRole.DESCENDANT: ">",
            RelationRole.FAMILY: "~",
        },
        toggle_key=".",
    )

    assert text is not None
    plain = text.plain
    assert "\n" not in plain
    chip_at = plain.index("▸")
    verb_at = plain.index("expand")
    first_segment_at = plain.index("< 1 ancestors")
    assert chip_at < verb_at < first_segment_at


def test_collapsed_rail_uses_the_passed_toggle_key() -> None:
    index, origin, relations = _relation_index()
    view = build_relation_view(index=index, origin=origin, relations=relations)
    text = _build_collapsed_rail(view, accent="#87D7FF", toggle_key="^r")

    assert text is not None
    assert "▸ ^r " in text.plain
    assert "▸ . " not in text.plain


def test_collapsed_empty_view_stays_hidden() -> None:
    origin = _target("current")
    relations = (
        _decl("ancestors", RelationKind.HIERARCHY, inverse="children"),
        _decl("children", RelationKind.HIERARCHY, inverse="ancestors"),
    )
    index = build_relation_index(
        pane_id="patches",
        relations=relations,
        edges=(),
        known_targets={origin},
    )
    view = build_relation_view(index=index, origin=origin, relations=relations)

    assert not view.keymap
    assert _build_collapsed_rail(view, accent="#87D7FF") is None


def test_patches_footer_appends_toggle_when_keymap_is_live() -> None:
    footer = KeybindingFooter()
    footer._app = SimpleNamespace(  # noqa: SLF001
        _relation_keymap=RelationKeymap(ancestors=(("<", _target("parent")),)),
        artifacts_relations_collapsed=False,
    )
    patch = make_patch(name="feature_a", status="Ready")

    labels = dict(footer._compute_available_bindings(patch))
    assert labels[footer._kd("toggle_relation_panel")] == "collapse relations"

    footer._app.artifacts_relations_collapsed = True  # noqa: SLF001
    labels = dict(footer._compute_available_bindings(patch))
    assert labels[footer._kd("toggle_relation_panel")] == "expand relations"


def _parent_child_patches() -> list[Patch]:
    patches = [
        make_patch(name="feature_root"),
        make_patch(name="feature_child", parent="feature_root"),
    ]
    for item in patches:
        item.project_display_name = "Alpha"
    return patches


async def _open_pane(
    page: AcePage,
    pane_id: str,
    widget_type: type,
    selector: str,
) -> Any:
    await page.press(page.artifacts_digit(pane_id))
    await page.expect_state("artifacts_subtab", pane_id)
    return page.query_one_widget(selector, widget_type)


def _relation_panel_for(pane: Any) -> RelationPanel:
    panel = pane.query_one(RelationPanel)
    assert isinstance(panel, RelationPanel)
    return panel


@pytest.mark.asyncio
async def test_dot_collapses_and_expands_on_each_relations_pane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads = beads_snapshot(tmp_path)
    plans = plans_snapshot(tmp_path)
    files = files_snapshot(
        (
            LogicalFile(
                logical_id="doc",
                label="doc",
                kind="file",
                versions=(
                    FileVersion(
                        version_id="v1",
                        logical_id="doc",
                        label="doc",
                        kind="file",
                        origin="ref",
                        origins=frozenset({"ref"}),
                        created_at=None,
                        agents=(),
                        projects=("alpha",),
                    ),
                    FileVersion(
                        version_id="v2",
                        logical_id="doc",
                        label="doc",
                        kind="file",
                        origin="ref",
                        origins=frozenset({"ref"}),
                        created_at=None,
                        agents=(),
                        projects=("alpha",),
                    ),
                ),
                agents=(),
                projects=("alpha",),
                origins=frozenset({"ref"}),
                latest_seen_at=None,
            ),
        ),
        project="alpha",
    )
    raw_stitches = stitches_result()
    child_entry = raw_stitches.commits[0]
    parent_entry = raw_stitches.commits[1]
    child_commit = _replace(
        child_entry.commit, parent_ids=(parent_entry.commit.full_id,)
    )
    stitches = _replace(
        raw_stitches,
        commits=(_replace(child_entry, commit=child_commit), parent_entry),
    )
    load_counts = {"beads": 0, "plans": 0, "files": 0, "stitches": 0}

    def load_beads(_project: str | None, **_kwargs: object) -> Any:
        load_counts["beads"] += 1
        return beads

    def load_plans(_project: str | None, **_kwargs: object) -> Any:
        load_counts["plans"] += 1
        return plans

    def load_files(
        _project: str | None,
        _limit: int | None = None,
        **_kwargs: object,
    ) -> Any:
        load_counts["files"] += 1
        return files

    def load_stitches(**_kwargs: object) -> VcsLogResult:
        load_counts["stitches"] += 1
        return stitches

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        load_beads,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        load_plans,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.files_pane.load_files_snapshot",
        load_files,
    )
    monkeypatch.setattr(commits_module, "run_vcs_log", load_stitches)
    monkeypatch.setattr("sase.vcs_log.run_vcs_log", load_stitches)
    monkeypatch.setattr(commits_module, "load_commit_diff_text", lambda _spec: "")

    cases = (
        ("patches", "#artifacts-patches-pane", ArtifactsPatchesPane),
        ("beads", "#artifacts-beads-pane", ArtifactsBeadsPane),
        ("ref:plan", "#artifacts-plans-pane", ArtifactsPlansPane),
        ("files", "#artifacts-files-pane", ArtifactsFilesPane),
        ("stitches", "#artifacts-stitches-pane", CommitsPane),
    )

    async with AcePage(query='"feature"', patches=_parent_child_patches()) as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        patch_pane = page.query_one_widget(
            "#artifacts-patches-pane", ArtifactsPatchesPane
        )
        child_target = ArtifactEntryTarget(
            pane_id="patches",
            parts=(page.app.patches[1].project_name, "feature_child"),
        )
        assert patch_pane.select_entry_target(child_target)
        page.app._sync_active_artifacts_entry_state()
        await page.pause()

        seen: list[str] = []
        for pane_id, selector, widget_type in cases:
            pane = await _open_pane(page, pane_id, widget_type, selector)
            if pane_id == "beads":
                await page.wait_for(
                    lambda _state, current=pane: current.snapshot is not None
                )
                assert pane.select_entry_target(
                    ArtifactEntryTarget(
                        pane_id="beads", parts=("alpha", "epic", "alpha-1")
                    )
                )
            elif pane_id == "ref:plan":
                await page.wait_for(
                    lambda _state, current=pane: current.snapshot is plans
                )
                await page.press("j")
            elif pane_id == "files":
                await page.wait_for(
                    lambda _state, current=pane: current.snapshot is not None
                )
            elif pane_id == "stitches":
                await page.wait_for(
                    lambda _state, current=pane: current.result is not None
                )
                targets = pane.entry_targets()
                assert targets, "stitches pane has no selectable commits"
                pane.select_entry_target(targets[0])
            pane.refresh_relation_panel()
            await page.pause()
            panel = _relation_panel_for(pane)
            assert panel.display, f"{pane_id} relation panel stayed hidden"
            assert panel.has_class("-collapsed"), (
                f"{pane_id} relation panel should start collapsed"
            )
            rail = _plain(panel)
            assert "\n" not in rail
            assert "▸" in rail
            loads_before = dict(load_counts)
            before_rows = len(getattr(pane, "entry_targets", lambda: ())())
            await page.press(".")
            await page.pause()
            assert page.app.artifacts_relations_collapsed is False
            assert not panel.has_class("-collapsed")
            assert panel.border_title == "▾ RELATIONS"
            assert panel.border_subtitle.endswith("collapse")
            await page.press(".")
            await page.pause()
            assert page.app.artifacts_relations_collapsed is True
            assert panel.has_class("-collapsed")
            assert panel.border_title == ""
            assert panel.border_subtitle == ""
            if before_rows:
                assert len(pane.entry_targets()) == before_rows
            assert load_counts == loads_before
            seen.append(pane_id)
        assert seen == [pane_id for pane_id, _selector, _widget_type in cases]


@pytest.mark.asyncio
async def test_collapsed_state_persists_across_subtabs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A toggle away from the default-collapsed state persists across sub-tabs."""
    value = beads_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )
    async with AcePage(query='"feature"', patches=_parent_child_patches()) as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        pane.select_entry_target(
            ArtifactEntryTarget(
                pane_id="patches",
                parts=(page.app.patches[1].project_name, "feature_child"),
            )
        )
        page.app._sync_active_artifacts_entry_state()
        await page.pause()
        assert page.app.artifacts_relations_collapsed is True
        await page.press(".")
        await page.pause()
        assert page.app.artifacts_relations_collapsed is False
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        beads_pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: beads_pane.snapshot is not None)
        assert page.app.artifacts_relations_collapsed is False
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        assert page.app.artifacts_relations_collapsed is False
        assert not _relation_panel_for(pane).has_class("-collapsed")


@pytest.mark.asyncio
async def test_collapsed_rail_keeps_keymap_and_footer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = beads_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        epic = ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        phase = ArtifactEntryTarget(
            pane_id="beads", parts=("alpha", "phase", "alpha-1.2")
        )
        assert pane.select_entry_target(epic)
        pane.set_selected_epic_expanded(True)
        assert pane.select_entry_target(phase)
        pane.refresh_relation_panel()
        await page.pause()
        panel = _relation_panel_for(pane)
        assert panel.has_class("-collapsed")
        rail = _plain(panel)
        assert "parent" in rail
        footer = dict(pane.conditional_footer_entries())
        assert footer["toggle_relation_panel"] == "expand relations"
        assert page.app._relation_keymap.ancestors
        await page.press("<")
        await page.pause()
        assert pane.selected_entry_target() == epic


def test_relations_expanded_config_true_starts_expanded() -> None:
    from sase.ace.tui.app import AceApp

    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {"artifacts": {"relations_expanded": True}}},
    ):
        app = AceApp(auto_start_axe=False)

    assert app.artifacts_relations_collapsed is False


def test_relations_expanded_config_absent_starts_collapsed() -> None:
    from sase.ace.tui.app import AceApp

    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {}},
    ):
        app = AceApp(auto_start_axe=False)

    assert app.artifacts_relations_collapsed is True


@pytest.mark.asyncio
async def test_configured_toggle_key_appears_in_rail_and_rebinding_changes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = beads_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"keymaps": {"app": {"toggle_relation_panel": "f9"}}}},
    )
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        epic = ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        assert pane.select_entry_target(epic)
        pane.refresh_relation_panel()
        await page.pause()
        panel = _relation_panel_for(pane)
        assert panel.has_class("-collapsed")
        rail = _plain(panel)
        assert "▸ f9 " in rail
        assert "▸ . " not in rail

        await page.press("f9")
        await page.pause()
        assert page.app.artifacts_relations_collapsed is False


@pytest.mark.asyncio
async def test_clicking_collapsed_rail_expands_and_expanded_click_is_a_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = beads_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        epic = ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        assert pane.select_entry_target(epic)
        pane.refresh_relation_panel()
        await page.pause()
        panel = _relation_panel_for(pane)
        assert panel.has_class("-collapsed")

        await page.click("#beads-relation-panel")
        await page.pause()
        assert page.app.artifacts_relations_collapsed is False
        assert not panel.has_class("-collapsed")

        await page.click("#beads-relation-panel")
        await page.pause()
        assert page.app.artifacts_relations_collapsed is False
        assert not panel.has_class("-collapsed")


@pytest.mark.asyncio
async def test_narrow_terminal_keeps_expand_chip_and_verb_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = beads_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )
    async with AcePage(initial_tab="patches", size=(80, 40)) as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        epic = ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        phase = ArtifactEntryTarget(
            pane_id="beads", parts=("alpha", "phase", "alpha-1.2")
        )
        assert pane.select_entry_target(epic)
        pane.set_selected_epic_expanded(True)
        assert pane.select_entry_target(phase)
        pane.refresh_relation_panel()
        await page.pause()
        panel = _relation_panel_for(pane)
        assert panel.has_class("-collapsed")
        rendered = "".join(segment.text for segment in panel.render_line(0))
        assert "▸" in rendered
        assert "expand" in rendered


@pytest.mark.asyncio
async def test_x_toggles_reverted_and_dot_does_not() -> None:
    patches = [
        make_patch(name="feature_ready", status="Ready"),
        make_patch(name="feature_reverted", status="Reverted"),
    ]
    async with AcePage(query='"feature"', patches=patches) as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        assert page.app.hide_reverted is True
        visible_before = {patch.name for patch in page.app.patches}
        assert "feature_reverted" not in visible_before
        await page.press(".")
        await page.pause()
        assert page.app.hide_reverted is True
        assert {patch.name for patch in page.app.patches} == visible_before
        await page.press("X")
        await page.pause()
        assert page.app.hide_reverted is False
        assert any(patch.name == "feature_reverted" for patch in page.app.patches)

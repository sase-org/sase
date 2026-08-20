"""Ctrl+J / Ctrl+K rewrite the Artifacts host-owned ``limit:`` cap."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.query.limit_token import extract_limit
from sase.ace.testing import AcePage
from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.widgets.artifacts import beads_pane
from sase.ace.tui.widgets.artifacts.bead_filter_bar import BeadFilterBar
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.files_filter_session import FilesFilterSessionMixin
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.bead.filter_query import to_query_string
from tests.ace.tui._artifacts_beads_helpers import snapshot
from tests.ace.tui.test_artifacts_relation_key_resolution import _KeyResolutionApp


def _available(app: object, action: str) -> bool:
    return check_app_action(app, action, (), lambda _action, _params: True) is not False


def test_artifacts_paging_actions_are_artifacts_only() -> None:
    artifacts = _KeyResolutionApp(tab="artifacts", pane_key="beads")
    agents = _KeyResolutionApp(tab="agents")
    prompt_open = _KeyResolutionApp(tab="artifacts", pane_key="patches")
    prompt_open._prompt_input_active = lambda: True  # type: ignore[method-assign]

    assert _available(artifacts, "artifacts_load_more")
    assert _available(artifacts, "artifacts_unload")
    assert not _available(agents, "artifacts_load_more")
    assert not _available(agents, "artifacts_unload")
    assert _available(agents, "next_agent_metadata_section")
    assert not _available(prompt_open, "artifacts_load_more")
    assert not _available(prompt_open, "artifacts_unload")


def test_files_grows_incomplete_snapshot_when_cap_outruns_loaded_page() -> None:
    calls: list[tuple[bool, bool]] = []
    fake = SimpleNamespace(
        _snapshot=SimpleNamespace(
            complete=False, load_error=None, rows=(object(),) * 3
        ),
        _request_load=lambda force, full: calls.append((force, full)),
    )

    FilesFilterSessionMixin._maybe_grow_files_snapshot(fake, 4)
    FilesFilterSessionMixin._maybe_grow_files_snapshot(fake, 2)
    fake._snapshot.complete = True
    FilesFilterSessionMixin._maybe_grow_files_snapshot(fake, None)

    assert calls == [(False, True)]


async def test_default_queries_include_page_size_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        patches_query = page.app.query_string
        _remainder, patches_cap = extract_limit(patches_query)
        assert patches_cap == 100
        assert "limit:100" in patches_query

        await page.press("1")
        stitches = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        assert stitches.filters.limit == 100

        await page.press("3")
        beads = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: beads.snapshot is value)
        assert beads.filters.limit == 100
        assert to_query_string(beads.filters) == "-status:closed limit:100"

        await page.press(page.artifacts_digit("files"))
        files = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(lambda _state: files.filters.limit == 100)
        assert files.filters.limit == 100

        await page.press(page.artifacts_digit("ref:plan"))
        plans = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        await page.wait_for(lambda _state: plans.filters.limit == 100)
        assert plans.filters.limit == 100


async def test_beads_ctrl_j_grows_limit_and_ctrl_k_returns_to_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr("sase.ace.config.get_ace_page_size", lambda: 2)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press("3")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        assert pane.filters.limit == 2
        before = len(pane.entry_targets())
        assert 0 < before <= 2

        await page.press("ctrl+j")
        await page.pause()
        assert pane.filters.limit == 4
        after = len(pane.entry_targets())
        assert after >= before
        assert after - before <= 2

        await page.press("ctrl+k")
        await page.pause()
        assert pane.filters.limit == 2
        assert len(pane.entry_targets()) <= 2

        await page.press("ctrl+k")
        await page.pause()
        assert pane.filters.limit == 2


async def test_beads_limit_all_then_ctrl_k_introduces_page_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press("3")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        pane.apply_host_limit_query("-status:closed limit:all")
        assert pane.filters.limit is None

        page.app.action_artifacts_unload()
        assert pane.filters.limit == 100
        assert "limit:100" in to_query_string(pane.filters)


async def test_custom_page_size_is_honored_on_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.ace.config.get_ace_page_size", lambda: 25)
    monkeypatch.setattr(
        "sase.ace.tui.actions._state_init_runtime.get_ace_page_size",
        lambda: 25,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        _remainder, cap = extract_limit(page.app.query_string)
        assert cap == 25

        page.app.action_artifacts_load_more()
        assert extract_limit(page.app.query_string)[1] == 50

        page.app.action_artifacts_unload()
        assert extract_limit(page.app.query_string)[1] == 25


async def test_patches_query_history_returns_to_pre_ctrl_j_query() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        original = page.app.query_string
        assert extract_limit(original)[1] == 100

        page.app.action_artifacts_load_more()
        assert extract_limit(page.app.query_string)[1] == 200
        assert page.app.query_string != original

        page.app.action_prev_query()
        assert page.app.query_string == original
        assert extract_limit(page.app.query_string)[1] == 100


async def test_open_filter_editor_updates_text_on_ctrl_j(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        beads_pane,
        "load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press("3")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        bar = pane.query_one(BeadFilterBar)

        await page.press("/")
        await page.pause()
        assert pane._filter_session_open

        await page.press("ctrl+j")
        await page.pause()
        assert pane._filter_session_open
        assert pane.filters.limit == 200
        assert "limit:200" in bar._editor().text  # type: ignore[union-attr]


async def test_artifacts_prompt_bar_ctrl_k_still_opens_history() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press("space")
        await page.pause()
        page.query_one_widget(".prompt-input", PromptTextArea)
        await page.press("h", "i", "ctrl+k")
        await page.expect_modal("PromptHistoryModal")


async def test_agents_tab_ctrl_j_does_not_rewrite_artifacts_query() -> None:
    async with AcePage(initial_tab="agents") as page:
        original = page.app.query_string
        page.app.action_artifacts_load_more()
        assert page.app.query_string == original
        assert not _available(page.app, "artifacts_load_more")
        assert _available(page.app, "next_agent_metadata_section")

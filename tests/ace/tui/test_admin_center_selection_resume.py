"""Real opener/resume coverage for every selectable Admin Center surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from rich.text import Text
from textual.widgets import OptionList, Tree

from sase.ace.testing import AcePage
from sase.ace.tui.logs import LogSource
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import logs_pane as lp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.ace.tui.modals.logs_pane import LogsPane
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.ace.tui.modals.project_inventory_panes import (
    RepoInventoryPane,
    WorkspaceInventoryPane,
)
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.ace.tui.modals.tasks_pane import TasksPane
from sase.ace.tui.modals.xprompt_browser_pane import XPromptBrowserPane
from sase.ace.tui.util.selection import restore_selection_by_identity

from tests.ace.tui._config_pane_widget_helpers import _fixture_view
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _patch_catalog,
)
from tests.ace.tui.modals.test_project_inventory_subtabs import (
    _patch_inventory_data,
)
from tests.ace.tui._tasks_pane_helpers import (
    patch_store_loader as _patch_store_loader,
    queue as _queue,
    task as _task,
)
from tests.ace.tui.test_xprompt_browser_load_keymap import _md_xprompt


@dataclass(frozen=True)
class _ResumeCase:
    surface: str
    tab_key: str
    setup_keys: tuple[str, ...] = ()
    move_key: str = "j"


_CASES = (
    _ResumeCase("config", "1"),
    _ResumeCase("logs", "2"),
    _ResumeCase("projects", "3"),
    _ResumeCase("repos", "3", ("right_square_bracket",)),
    _ResumeCase(
        "workspaces",
        "3",
        ("right_square_bracket", "right_square_bracket"),
    ),
    _ResumeCase("tasks", "5"),
    _ResumeCase("plugins", "6", ("right_square_bracket",)),
    _ResumeCase(
        "agent-clis",
        "6",
        ("right_square_bracket", "right_square_bracket"),
    ),
    _ResumeCase("xprompts", "7", move_key="ctrl+n"),
)


def _patch_all_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> object:
    view = _fixture_view()
    config_result = cp._LoadResult(view=view, error=None, token=("resume", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kwargs: config_result)
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: None)

    sources = [
        LogSource(
            id=f"source-{index}",
            title=f"Source {index}",
            description=f"Source {index}",
            path=tmp_path / f"source-{index}.log",
            render="text",
        )
        for index in range(3)
    ]
    monkeypatch.setattr(lp, "log_sources", lambda: list(sources))

    def _load_logs(
        selected_index: int,
        selected_source_id: str | None = None,
    ) -> lp._LogPaneLoadResult:
        selected_index = restore_selection_by_identity(
            sources,
            prior_identity=selected_source_id,
            prior_visual_row=selected_index,
            identity_fn=lambda source: source.id,
        )
        return lp._LogPaneLoadResult(
            sources=list(sources),
            options=[(f"log__{source.id}", Text(source.title)) for source in sources],
            active_count=0,
            selected_index=selected_index,
            detail=Text(sources[selected_index].id),
        )

    monkeypatch.setattr(lp, "_build_log_pane_load_result", _load_logs)
    _patch_inventory_data(monkeypatch)
    _patch_store_loader(monkeypatch, [])
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )

    prompt_paths = [tmp_path / f"prompt-{index}.md" for index in range(3)]
    for index, path in enumerate(prompt_paths):
        path.write_text(f"Prompt {index}.", encoding="utf-8")
    prompts = {
        f"prompt-{index}": _md_xprompt(
            f"prompt-{index}",
            f"Prompt {index}.",
            source_path=str(path),
        )
        for index, path in enumerate(prompt_paths)
    }
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: dict(prompts),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    return view


def _surface_selection(modal: ConfigCenterModal, surface: str) -> str | None:
    if surface == "config":
        node = modal.query_one(ConfigPane).query_one("#config-tree", Tree).cursor_node
        return node.data if node is not None and isinstance(node.data, str) else None
    if surface == "logs":
        pane = modal.query_one(LogsPane)
        option_list = pane.query_one("#log-source-list", OptionList)
    elif surface == "projects":
        pane = modal.query_one(ProjectsPane)
        option_list = pane.query_one("#projects-list", OptionList)
    elif surface == "repos":
        pane = modal.query_one(RepoInventoryPane)
        option_list = pane.query_one("#repos-list", OptionList)
    elif surface == "workspaces":
        pane = modal.query_one(WorkspaceInventoryPane)
        option_list = pane.query_one("#workspaces-list", OptionList)
    elif surface == "tasks":
        pane = modal.query_one(TasksPane)
        option_list = pane.query_one("#tasks-list", OptionList)
    elif surface == "plugins":
        pane = modal.query_one(PluginsBrowserPane)
        option_list = pane.query_one("#plugins-list", OptionList)
    elif surface == "agent-clis":
        pane = modal.query_one(PluginsBrowserPane)
        option_list = pane.query_one("#agent-clis-list", OptionList)
    else:
        pane = modal.query_one(XPromptBrowserPane)
        option_list = pane.query_one("#browser-list", OptionList)
    highlighted = option_list.highlighted
    if highlighted is None:
        return None
    option_id = option_list.get_option_at_index(highlighted).id
    return str(option_id) if option_id is not None else None


def _detail_selection(modal: ConfigCenterModal, surface: str) -> str | None:
    if surface == "config":
        return modal.query_one(ConfigPane)._selected_path
    if surface == "logs":
        pane = modal.query_one(LogsPane)
        return pane._source_id_for_index(pane._selected_index)
    if surface == "projects":
        return modal.query_one(ProjectsPane)._selected_project_name()
    if surface == "repos":
        return modal.query_one(RepoInventoryPane)._selected_record_id()
    if surface == "workspaces":
        return modal.query_one(WorkspaceInventoryPane)._selected_record_id()
    if surface == "tasks":
        return modal.query_one(TasksPane)._selected_task_identity()
    if surface == "plugins":
        return modal.query_one(PluginsBrowserPane)._detail_name
    if surface == "agent-clis":
        return modal.query_one(PluginsBrowserPane)._agent_cli_detail_name
    item = modal.query_one(XPromptBrowserPane)._get_highlighted_item()
    return item.name if item is not None else None


def _normalized_selection(surface: str, selection: str | None) -> str | None:
    prefixes = {
        "logs": "log__",
        "tasks": "task__",
        "plugins": "plugin__",
        "agent-clis": "agent-cli__",
        "xprompts": "item__",
    }
    prefix = prefixes.get(surface)
    if selection is None or prefix is None:
        return selection
    return selection.removeprefix(prefix)


async def _wait_for_surface_ready(
    page: AcePage,
    modal: ConfigCenterModal,
    surface: str,
) -> None:
    if surface == "projects":
        await page.wait_for(
            lambda _s: modal.query_one("#projects-list", OptionList).option_count >= 2
        )
    elif surface in {"repos", "workspaces"}:
        pane_type = RepoInventoryPane if surface == "repos" else WorkspaceInventoryPane
        await page.wait_for(
            lambda _s: (
                not modal.query_one(pane_type)._loading
                and len(modal.query_one(pane_type)._filtered_records) >= 2
            )
        )
    elif surface == "tasks":
        await page.wait_for(
            lambda _s: modal.query_one("#tasks-list", OptionList).option_count >= 2
        )
    elif surface in {"plugins", "agent-clis"}:
        await page.wait_for(lambda _s: not modal.query_one(PluginsBrowserPane)._loading)
    elif surface == "logs":
        await page.wait_for(lambda _s: not modal.query_one(LogsPane)._loading)
    else:
        await page.wait_for(lambda _s: _surface_selection(modal, surface) is not None)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.surface)
async def test_real_opener_resume_restores_visible_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: _ResumeCase,
) -> None:
    _patch_all_surfaces(monkeypatch, tmp_path)
    tasks = [
        _task(
            f"task-{index}",
            label=f"sync task-{index}",
            status="success",
            age_seconds=index + 1,
        )
        for index in range(3)
    ]

    async with AcePage(initial_tab="agents") as page:
        page.app._task_queue = _queue(*tasks)
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        await page.press(case.tab_key)
        await page.wait_for(lambda _s: modal._active_tab is not None)
        if case.setup_keys:
            await page.press(*case.setup_keys)
        await _wait_for_surface_ready(page, modal, case.surface)

        before = _surface_selection(modal, case.surface)
        await page.press(case.move_key)
        await page.wait_for(
            lambda _s: _surface_selection(modal, case.surface) != before
        )
        selected = _surface_selection(modal, case.surface)
        normalized = _normalized_selection(case.surface, selected)
        await page.wait_for(
            lambda _s: _detail_selection(modal, case.surface) == normalized
        )

        await page.press("escape")
        await page.expect_no_modal()
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        resumed = page.app.screen
        assert isinstance(resumed, ConfigCenterModal)
        await page.press("number_sign")
        await page.wait_for(lambda _s: resumed._active_tab is not None)
        await _wait_for_surface_ready(page, resumed, case.surface)
        await page.wait_for(
            lambda _s: _surface_selection(resumed, case.surface) == selected
        )
        await page.wait_for(
            lambda _s: _detail_selection(resumed, case.surface) == normalized
        )

        assert _surface_selection(resumed, case.surface) == selected

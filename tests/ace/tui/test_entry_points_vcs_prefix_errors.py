"""Tests for TUI-facing VCS prefix detection failures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow import _entry_points
from sase.ace.tui.actions.agent_workflow._entry_points import EntryPointsMixin
from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import PromptBarMountMixin
from sase.history.prompt import PromptEntry
from sase.ace.tui.modals import SelectionItem


class _App(EntryPointsMixin):
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.prompt_launches: list[dict[str, Any]] = []
        self.editor_launches: list[dict[str, Any]] = []
        self.editor_prompts: list[str] = []
        self.finished_prompts: list[str] = []
        self.changespecs: list[Any] = []
        self.current_idx = 0
        self._last_custom_agent_selection = None
        self._prompt_context = None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _show_prompt_input_bar_for_home(self, **kwargs: Any) -> None:
        self.prompt_launches.append(kwargs)

    def _select_and_open_editor_for_home(self, **kwargs: Any) -> None:
        self.editor_launches.append(kwargs)

    def _open_editor_for_agent_prompt(self, prompt: str) -> str:
        self.editor_prompts.append(prompt)
        return f"edited: {prompt}"

    def _finish_agent_launch(self, prompt: str) -> None:
        self.finished_prompts.append(prompt)


class _EditorApp(EntryPointsMixin, PromptBarMountMixin):
    def __init__(self, *, editor_result: str | None = None) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.editor_prompts: list[str] = []
        self.finished_prompts: list[str] = []
        self.mounted: list[Any] = []
        self.prompt_launches: list[dict[str, Any]] = []
        self._prompt_context = None
        self.editor_result = editor_result

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _open_editor_for_agent_prompt(self, prompt: str) -> str:
        self.editor_prompts.append(prompt)
        if self.editor_result is not None:
            return self.editor_result
        return f"edited: {prompt}"

    def _finish_agent_launch(self, prompt: str) -> None:
        self.finished_prompts.append(prompt)

    def _unmount_prompt_bar(self) -> None:
        return None

    def mount(self, widget: Any) -> None:
        self.mounted.append(widget)


@pytest.fixture
def missing_workspace_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_project_file: str, _name: str) -> str:
        raise ValueError("No workspace plugin detected a workflow type")

    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(_entry_points, "_vcs_prompt_prefix", _raise)


def test_repeat_last_selection_reports_vcs_detection_error_without_launching(
    missing_workspace_plugin: None,
) -> None:
    app = _App()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Fix bug",
        item_type="cl",
        project_name="proj",
        cl_name="fix_bug",
    )

    app.action_start_agent_from_changespec()

    assert app.notifications == [
        (
            "Cannot start agent for fix_bug: "
            "No workspace plugin detected a workflow type",
            "error",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []


def test_start_last_vcs_xprompt_editor_opens_mru_prefix_and_launches_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
        lambda: ["#gh:sase", "#gh:old"],
    )
    app = _EditorApp()

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["#gh:sase "]
    assert app.finished_prompts == ["edited: #gh:sase "]
    assert app.notifications == []
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "sase"
    assert app._prompt_context.history_sort_key == "sase"


def test_start_last_vcs_xprompt_editor_warns_when_mru_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
        lambda: [],
    )
    app = _App()

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_launches == []
    assert app.prompt_launches == []
    assert app.notifications == [("No previous VCS xprompt", "warning")]


def test_start_last_vcs_xprompt_editor_cancel_records_prefilled_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled_prompts: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
        lambda: ["#gh:sase"],
    )

    def _record_cancelled_prompt(text: str, *, cancelled: bool = False) -> None:
        cancelled_prompts.append((text, cancelled))

    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt",
        _record_cancelled_prompt,
    )
    app = _EditorApp(editor_result="")

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["#gh:sase "]
    assert cancelled_prompts == [("#gh:sase", True)]
    assert app.notifications == [("No prompt from editor - cancelled", "warning")]
    assert app._prompt_context is None


def test_repeat_last_selection_clears_stale_missing_project_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_calls: list[bool] = []
    persisted_selection = SelectionItem(
        display_name="branch",
        item_type="cl",
        project_name="project",
        cl_name="branch",
    )

    def _unexpected_prefix(_project_file: str, _name: str) -> str:
        raise AssertionError("stale selections should not detect workspace type")

    monkeypatch.setattr(
        "sase.ace.last_agent_selection.load_last_agent_selection",
        lambda: persisted_selection,
    )
    monkeypatch.setattr(
        "sase.ace.last_agent_selection.clear_last_agent_selection",
        lambda: clear_calls.append(True) or True,
    )
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: False)
    monkeypatch.setattr(_entry_points, "_vcs_prompt_prefix", _unexpected_prefix)

    app = _App()

    app.action_start_agent_from_changespec()

    assert app.notifications == [
        (
            "Saved @/<space> selection is stale: "
            "project 'project' is not launchable; cleared saved selection",
            "warning",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []
    assert app._last_custom_agent_selection is None
    assert clear_calls == [True]


def test_quick_current_changespec_reports_vcs_detection_error_without_saving(
    missing_workspace_plugin: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[SelectionItem] = []
    monkeypatch.setattr(
        "sase.ace.last_agent_selection._save_last_agent_selection", saved.append
    )
    app = _App()
    app.changespecs = [
        SimpleNamespace(
            name="fix_bug",
            file_path="/tmp/proj/proj.sase",
            project_basename="proj",
        )
    ]

    app._start_agent_from_changespec_quick()

    assert app.notifications == [
        (
            "Cannot start agent for fix_bug: "
            "No workspace plugin detected a workflow type",
            "error",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []
    assert app._last_custom_agent_selection is None
    assert saved == []


def test_prompt_history_edit_first_uses_first_non_cancelled_modal_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.history.prompt.get_prompts_for_fzf",
        lambda current_branch, current_workspace, include_cancelled: [
            (
                "x target | cancelled",
                PromptEntry(
                    text="#gh:old cancelled prompt",
                    branch_or_workspace="target",
                    timestamp="260509_100000",
                    last_used="260509_130000",
                    workspace="home",
                    cancelled=True,
                ),
            ),
            (
                "* target | picked",
                PromptEntry(
                    text="picked prompt",
                    branch_or_workspace="target",
                    timestamp="260509_090000",
                    last_used="260509_120000",
                    workspace="home",
                ),
            ),
        ],
    )
    app = _App()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Target",
        item_type="cl",
        project_name="proj",
        cl_name="target",
    )

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == ["#gh:target picked prompt"]
    assert app.finished_prompts == ["edited: #gh:target picked prompt"]
    assert app.notifications == []
    assert app._prompt_context is not None
    assert app._prompt_context.history_sort_key == "target"


def test_prompt_history_edit_first_notifies_when_no_non_cancelled_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.history.prompt.get_prompts_for_fzf",
        lambda current_branch, current_workspace, include_cancelled: [
            (
                "x target | cancelled",
                PromptEntry(
                    text="#gh:old cancelled prompt",
                    branch_or_workspace="target",
                    timestamp="260509_100000",
                    last_used="260509_130000",
                    workspace="home",
                    cancelled=True,
                ),
            )
        ],
    )
    app = _App()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Target",
        item_type="cl",
        project_name="proj",
        cl_name="target",
    )

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == []
    assert app.finished_prompts == []
    assert app.notifications == [("No prompt history entry to edit", "warning")]
    assert app._prompt_context is None


def _patch_save_recorder(monkeypatch: pytest.MonkeyPatch) -> list[SelectionItem]:
    """Capture writes by ``save_last_agent_selection`` in an in-memory list."""
    saved: list[SelectionItem] = []

    def _record(selection: SelectionItem) -> bool:
        saved.append(selection)
        return True

    monkeypatch.setattr(
        "sase.ace.last_agent_selection._save_last_agent_selection", _record
    )
    return saved


def test_quick_changespec_skips_save_for_non_launchable_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bogus project_basename must not be persisted, but the prompt bar still mounts."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: False,
    )
    saved = _patch_save_recorder(monkeypatch)

    app = _App()
    app.changespecs = [
        SimpleNamespace(
            name="branch",
            file_path="/tmp/project/project.sase",
            project_basename="project",
        )
    ]

    app._start_agent_from_changespec_quick()

    assert saved == []
    assert app._last_custom_agent_selection is None
    assert len(app.prompt_launches) == 1
    assert app.prompt_launches[0]["initial_text"] == "#gh:branch "


def test_quick_agent_skips_save_for_non_launchable_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale agent.project_file must not get persisted as last selection."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: False,
    )
    saved = _patch_save_recorder(monkeypatch)

    agent = SimpleNamespace(
        project_file="/tmp/project/project.sase",
        cl_name="branch",
        is_project_agent=False,
    )

    class _AppWithAgent(_App):
        def _get_selected_agent(self) -> Any:
            return agent

    app = _AppWithAgent()

    app._start_agent_from_agent_quick()

    assert saved == []
    assert app._last_custom_agent_selection is None
    assert len(app.prompt_launches) == 1


def test_edit_and_relaunch_skips_save_for_non_launchable_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale project_file in edit-and-relaunch must not be persisted."""
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: False,
    )
    saved = _patch_save_recorder(monkeypatch)

    class _AppEdit(_App):
        def __init__(self) -> None:
            super().__init__()
            self.mounted: list[Any] = []

        def _unmount_prompt_bar(self) -> None:
            return None

        def mount(self, widget: Any) -> None:
            self.mounted.append(widget)

    app = _AppEdit()

    app._edit_and_relaunch_agent(
        raw_prompt="Do work",
        project_file="/tmp/project/project.sase",
        cl_name="branch",
        is_project_agent=False,
    )

    assert saved == []
    assert app._last_custom_agent_selection is None
    assert len(app.mounted) == 1

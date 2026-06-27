"""Shared fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import json
import os
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.ace.tui.modals.logs_pane import LogsPane
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.ace.tui.modals.tasks_pane import TasksPane
from sase.ace.tui.task_queue import TaskInfo
from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory, config_field_model
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.logs import (
    events_log_path,
    launch_failures_log_path,
    runs_log_path,
    tui_log_path,
)
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from tests.ace.tui.test_plugins_browser_pane import (
    _NOW as _PLUGINS_NOW,
    _catalog,
    _core_versions,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    project_records,
    wait_for_visual_idle,
)

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03
_FIXED_LOG_MTIME = int(datetime(2026, 6, 17, 14, 30, tzinfo=UTC).timestamp())
_FIXED_TASK_NOW = datetime(2026, 6, 26, 12, 0, 0)

_LONG_QUERY = (
    "status:running and (agent:planner or agent:coder) and "
    "project:visual_demo and not tag:archived and updated_after:2026-01-01"
)


def _config_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timezone": {
                "type": "string",
                "default": "America/New_York",
                "description": "IANA timezone used for all dates.",
            },
            "use_chezmoi": {
                "type": "boolean",
                "default": False,
                "description": "Manage home-dir config via chezmoi.",
            },
            "axe": {
                "type": "object",
                "additionalProperties": False,
                "description": "Background AXE engine settings.",
                "properties": {
                    "max_hook_runners": {
                        "type": "integer",
                        "default": 3,
                        "description": "Max concurrent hook runners.",
                    },
                    "query": {
                        "type": "string",
                        "default": "",
                        "description": "Default AXE query filter.",
                    },
                    "chop_script_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "Directories scanned for chop scripts.",
                    },
                },
            },
            "linked_repos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "default": [],
                "description": "Linked sibling repositories.",
            },
            "sibling_repos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "description": "Deprecated alias for linked_repos.",
            },
        },
    }


def _config_layers(*, long_value: bool = False) -> list[ConfigLayer]:
    user_axe: dict[str, Any] = {"max_hook_runners": 5}
    if long_value:
        user_axe["query"] = _LONG_QUERY
    return [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "timezone": "America/New_York",
                "use_chezmoi": False,
                "axe": {
                    "max_hook_runners": 3,
                    "query": "",
                    "chop_script_dirs": ["builtin"],
                },
                "linked_repos": [{"name": "core"}],
            },
        ),
        ConfigLayer(
            name="user",
            path="/home/visual/.config/sase/sase.yml",
            exists=True,
            list_strategy="replace",
            data={
                "timezone": "US/Pacific",
                "axe": user_axe,
                "sibling_repos": [{"name": "legacy"}],
            },
        ),
        ConfigLayer(
            name="overlay:sase_work.yml",
            path="/home/visual/.config/sase/sase_work.yml",
            exists=True,
            list_strategy="concatenate",
            data={"axe": {"chop_script_dirs": ["work"]}},
        ),
        ConfigLayer(
            name="overlay:missing.yml",
            path="/home/visual/.config/sase/missing.yml",
            exists=False,
            list_strategy="concatenate",
            data={},
        ),
    ]


def _build_view(schema: dict[str, Any], layers: list[ConfigLayer]) -> cp.ConfigPaneView:
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=layers,
    ):
        inventory = build_config_inventory(schema=schema)
    field_model = config_field_model(schema)
    return cp.ConfigPaneView.build(field_model, inventory)


def _patch_config_view(
    monkeypatch: pytest.MonkeyPatch, view: cp.ConfigPaneView | None
) -> None:
    result = cp._LoadResult(view=view, error=None, token=("visual", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: result)


def _xprompts() -> dict[str, Workflow]:
    return {
        "review": Workflow(
            name="review",
            description="Review a selected diff for correctness.",
            inputs=[
                InputArg(
                    name="diff",
                    type=InputType.PATH,
                    description="Diff file to inspect.",
                )
            ],
            steps=[WorkflowStep(name="prompt", prompt_part="Review {{ diff }}.")],
            source_path="/home/visual/.xprompts/review.md",
        ),
        "ship": Workflow(
            name="ship",
            description="Ship the current change end-to-end.",
            steps=[WorkflowStep(name="run", agent="ship the change")],
            source_path="/home/visual/.xprompts/ship.yml",
        ),
    }


def _patch_xprompt_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = _xprompts()
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: dict(prompts),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.classify_source",
        lambda source_path: (
            "Home ~/.xprompts/",
            source_path.replace("/home/visual", "~"),
            True,
        ),
    )


def _patch_plugins_catalog(
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: Any | None = "default",
    error: str | None = None,
    core_versions: Any | None = None,
) -> None:
    """Stub the Updates pane's plugin catalog load with a deterministic result."""
    resolved = _catalog() if catalog == "default" else catalog
    result = pbp._PluginsLoadResult(
        catalog=resolved,
        error=error,
        now=_PLUGINS_NOW,
        core_versions=core_versions or _core_versions(),
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: result)
    monkeypatch.setattr(pbp, "_collect_installed_core_versions", _core_versions)


def _patch_project_records(
    monkeypatch: pytest.MonkeyPatch,
    records: list[ProjectRecordWire] | None = None,
) -> None:
    """Feed the always-mounted Projects pane deterministic lifecycle records.

    Overrides the ``conftest`` autouse stub (which returns an empty list to keep
    other Admin Center snapshots deterministic) so the Projects tab renders a
    stable spread of states, claims, aliases, and warnings.
    """
    resolved = project_records() if records is None else records
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: list(resolved),
    )


def _write_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (_FIXED_LOG_MTIME, _FIXED_LOG_MTIME))


def _seed_logs_tab_files() -> None:
    _write_log(
        launch_failures_log_path(),
        "\n".join(
            [
                "=" * 72,
                "[2026-06-17 14:30:00 UTC] fanout launch failure: visual-auth",
                "  kind: fanout",
                "  project: sase",
                "  workspace: 11",
                "  error: RuntimeError: provider exited before writing metadata",
                "",
                "  traceback:",
                (
                    '    File "src/sase/ace/tui/actions/agent_workflow/'
                    '_launch_tasks.py", line 89, in _finish'
                ),
                "      raise RuntimeError('provider exited before writing metadata')",
                "    RuntimeError: provider exited before writing metadata",
                "",
                "  prompt preview:",
                "    Build the Operations / Logs visual snapshot and verify it is readable.",
            ]
        )
        + "\n",
    )
    _write_log(
        tui_log_path(),
        "\n".join(
            [
                "2026-06-17 14:28:00 WARNING sase.ace.tui: retrying stale launch task",
                (
                    "2026-06-17 14:30:00 ERROR sase.ace.tui: launch failed; "
                    "wrote launch_failures.log"
                ),
            ]
        )
        + "\n",
    )
    _write_log(
        runs_log_path(),
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "260617_142700",
                        "event": "agent_run",
                        "workflow": "visual",
                        "project": "sase",
                        "workspace_num": 11,
                        "status": "FAILED",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "260617_143000",
                        "event": "agent_run",
                        "workflow": "visual",
                        "project": "sase",
                        "workspace_num": 11,
                        "status": "DONE",
                    }
                ),
            ]
        )
        + "\n",
    )
    _write_log(
        events_log_path(),
        json.dumps(
            {
                "timestamp": "260617_143000",
                "event": "agent_revive_failed",
                "project": "sase",
                "name": "visual-auth",
                "outcome": "failure",
            }
        )
        + "\n",
    )


def _task(
    task_id: str,
    *,
    label: str,
    status: str,
    age_seconds: int,
    output: str = "",
    error: str | None = None,
    live_output: str | None = None,
) -> TaskInfo:
    started_at = _FIXED_TASK_NOW.replace(tzinfo=None) - timedelta(seconds=age_seconds)
    info = TaskInfo(
        task_id=task_id,
        task_type=label.split()[0],
        cl_name="",
        project_file="",
        status=status,
        message=f"{label} complete",
        started_at=started_at,
        display_name=label,
        finished_at=started_at if status != "running" else None,
        output=output,
        error=error,
    )
    if live_output is not None:
        info._live_buffer = io.StringIO(live_output)
    return info


def _seed_tasks_tab_queue(app: Any) -> None:
    queue = app._task_queue
    queue._tasks = {
        task.task_id: task
        for task in (
            _task(
                "sync",
                label="sync sase-42",
                status="running",
                age_seconds=3,
                live_output=(
                    "Syncing sase-42...\n"
                    "remote: Enumerating objects: 1240\n"
                    "remote: Counting objects: 100% (1240/1240)\n"
                    "Receiving objects: 100% (88/88), 34.2 KiB\n"
                ),
            ),
            _task(
                "launch",
                label="launch fanout visual-auth",
                status="running",
                age_seconds=12,
                live_output=(
                    "Launching 3 agents for visual-auth\n"
                    "planner: queued\n"
                    "coder: running\n"
                    "reviewer: waiting for workspace\n"
                ),
            ),
            _task(
                "mail",
                label="mail sase-41",
                status="success",
                age_seconds=142,
                output="Mailed sase-41 to reviewers.\n",
            ),
            _task(
                "rebase",
                label="rebase sase-40",
                status="error",
                age_seconds=315,
                output="CONFLICT (content): src/sase/ace/tui/app.py\n",
                error="merge conflict",
            ),
            _task(
                "accept",
                label="accept sase-39",
                status="success",
                age_seconds=580,
                output="Accepted mentor proposal and refreshed ChangeSpec.\n",
            ),
        )
    }


async def _open_modal(page: AcePage, initial_tab: CenterTab) -> ConfigCenterModal:
    modal = ConfigCenterModal(initial_tab=initial_tab)
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await wait_for_visual_idle(page)
    return modal


async def _open_config_modal(page: AcePage) -> tuple[ConfigCenterModal, ConfigPane]:
    modal = ConfigCenterModal(initial_tab="config")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    pane = modal.query_one("#config", ConfigPane)
    await page.wait_for(lambda _s: bool(pane._node_by_path))
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_projects_modal(
    page: AcePage,
) -> tuple[ConfigCenterModal, ProjectsPane]:
    modal = ConfigCenterModal(initial_tab="projects")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#projects-list")))
    pane = modal.query_one("#projects", ProjectsPane)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_logs_modal(page: AcePage) -> tuple[ConfigCenterModal, LogsPane]:
    modal = ConfigCenterModal(
        initial_tab="operations",
        initial_operations_subtab="logs",
    )
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#logs")))
    pane = modal.query_one("#logs", LogsPane)
    await page.wait_for(lambda _s: not pane._loading)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_tasks_modal(page: AcePage) -> tuple[ConfigCenterModal, TasksPane]:
    modal = ConfigCenterModal(
        initial_tab="operations",
        initial_operations_subtab="tasks",
    )
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#tasks")))
    pane = modal.query_one("#tasks", TasksPane)
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_plugins_modal(
    page: AcePage,
) -> tuple[ConfigCenterModal, PluginsBrowserPane]:
    modal = ConfigCenterModal(initial_tab="updates")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#updates")))
    pane = modal.query_one("#updates", PluginsBrowserPane)
    await page.wait_for(lambda _s: not pane._loading)
    await wait_for_visual_idle(page)
    return modal, pane


async def _wait_for_plugins_detail(page: AcePage, pane: PluginsBrowserPane) -> None:
    """Let the pane's debounced detail repaint settle before snapshotting."""
    debouncer = pane._detail_debouncer
    if debouncer is not None:
        await page.wait_for(lambda _s: not debouncer.is_pending)
    await wait_for_visual_idle(page)

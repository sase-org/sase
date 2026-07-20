"""Integration coverage for saved agent group save/revival."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Static

from sase.ace import dismissed_agents
from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal
from sase.ace.tui.modals.save_agent_group_modal import SaveAgentGroupModal
from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.paths import sase_home
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


async def test_mark_save_preview_and_revive_saved_agent_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walk the Agents-tab m/s/R saved-group flow through preview and revive."""

    agent = _agent(
        cl_name="visual-polish",
        raw_suffix="20260527120000",
        agent_name="visual.worker",
        tribe="backend",
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    _patch_dismissed_archive_paths(monkeypatch, tmp_path)
    restored: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        AceApp,
        "_restore_agent_artifacts",
        lambda _app, restored_agent, *, parent_artifacts_dir=None: restored.append(
            (restored_agent.raw_suffix or "", parent_artifacts_dir)
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._marking.sync_dismissed_agent_artifact_index",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._revive.sync_dismissed_agent_artifact_index",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._revive.upsert_agent_artifact_index_artifacts",
        lambda *_args, **_kwargs: None,
    )

    async with AcePage(
        query='"visual"',
        changespecs=[make_changespec(name="visual-polish")],
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 1)

        await page.press("m")
        await page.press("s")
        await page.expect_modal("SaveAgentGroupModal")
        save_modal = page.app.screen
        assert isinstance(save_modal, SaveAgentGroupModal)
        save_modal.query_one(
            "#save-agent-group-name-input", SingleLineVimTextArea
        ).text = "Visual backend"
        await page.press("enter")
        await page.expect_no_modal()
        await page.expect_state("agent_count", 0)
        await _wait_until(
            lambda: bool(dismissed_agents.list_dismissed_agent_groups().groups)
        )

        group = dismissed_agents.list_dismissed_agent_groups().groups[0]
        assert group.name == "Visual backend"
        assert group.title == "1 agent from @backend"
        assert group.agent_count == 1

        await page.press("R")
        await page.expect_modal("SavedAgentGroupRevivalModal")
        modal = page.app.screen
        assert isinstance(modal, SavedAgentGroupRevivalModal)
        preview = modal.query_one("#saved-agent-group-preview", Static)
        assert "Visual backend" in _static_plain(preview)
        assert "visual.worker" in _static_plain(preview)

        await page.press("enter")
        await page.expect_no_modal()
        await _wait_until(lambda: bool(restored))

    assert restored == [("20260527120000", None)]
    revived_group = dismissed_agents.load_dismissed_agent_group(group.group_id)
    assert revived_group is not None
    assert revived_group.times_revived == 1
    assert revived_group.agent_refs[0].raw_suffix == "20260527120000"


async def test_saved_group_revive_restores_deleted_artifacts_and_tribe_real_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S/R revive restores deleted markers from the bundle and keeps the tribe."""

    _patch_non_agent_startup(monkeypatch)
    project_file, artifacts_dir = _write_done_agent_artifacts(
        project="saved-group-real",
        cl_name="visual-polish",
        raw_suffix="20260527123000",
        agent_name="visual.worker",
        tribe="backend",
    )

    async with AcePage(
        query='"visual"',
        changespecs=[
            make_changespec(name="visual-polish", file_path=str(project_file))
        ],
        initial_tab="agents",
        startup_policy="real",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 1)
        assert page.app._agents[0].tribe == "backend"

        await page.press("m")
        await page.press("s")
        await page.expect_modal("SaveAgentGroupModal")
        await page.press("enter")
        await page.expect_no_modal()
        await page.expect_state("agent_count", 0)
        await _wait_until(
            lambda: bool(dismissed_agents.list_dismissed_agent_groups().groups)
        )

        group = dismissed_agents.list_dismissed_agent_groups().groups[0]
        loaded_group = dismissed_agents.load_dismissed_agent_group(group.group_id)
        assert loaded_group is not None
        assert loaded_group.agent_refs[0].tribe == "backend"
        bundled = dismissed_agents.load_dismissed_bundles({"20260527123000"})
        assert [agent.tribe for agent in bundled] == ["backend"]

        shutil.rmtree(artifacts_dir)
        page.app._load_agents(full_history=True)
        await page.expect_state("agent_count", 0)

        await page.press("R")
        await page.expect_modal("SavedAgentGroupRevivalModal")
        await page.press("enter")
        await page.expect_no_modal()
        await _wait_until(
            lambda: any(
                agent.raw_suffix == "20260527123000" and agent.tribe == "backend"
                for agent in page.app._agents
            )
        )

        revived = next(
            agent for agent in page.app._agents if agent.raw_suffix == "20260527123000"
        )
        assert revived.tribe == "backend"
        assert (
            json.loads((artifacts_dir / "agent_meta.json").read_text())["tribe"]
            == "backend"
        )


async def test_agents_command_palette_exposes_save_marked_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Agents-tab palette exposes save/dismiss only after marks exist."""

    agent = _agent(raw_suffix="20260527121000")
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        query='"visual"',
        changespecs=[make_changespec(name="visual-polish")],
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.press("colon")
        await page.expect_modal("CommandPaletteModal")
        modal = page.app.screen
        assert isinstance(modal, CommandPaletteModal)
        assert "app.save_marked_agents" not in {spec.id for spec in modal._all_specs}
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("m")
        await page.press("colon")
        await page.expect_modal("CommandPaletteModal")
        modal = page.app.screen
        assert isinstance(modal, CommandPaletteModal)
        save_spec = next(
            spec for spec in modal._all_specs if spec.id == "app.save_marked_agents"
        )
        assert save_spec.label == "Save/dismiss marked agents"


async def test_lowercase_s_dispatches_by_active_tab(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lowercase s remains PR status on ChangeSpecs and saves marked agents on Agents."""

    agent = _agent(raw_suffix="20260527122000")
    patch_startup_loaders(monkeypatch, agents=[agent])
    _patch_dismissed_archive_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._marking.sync_dismissed_agent_artifact_index",
        lambda *_args, **_kwargs: None,
    )

    async with AcePage(
        query='"visual"',
        changespecs=[make_changespec(name="visual-polish", status="WIP")],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("s")
        await page.expect_modal("StatusModal")

    async with AcePage(
        query='"visual"',
        changespecs=[make_changespec(name="visual-polish")],
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.press("m")
        await page.press("s")
        await page.expect_modal("SaveAgentGroupModal")
        await page.press("enter")
        await page.expect_no_modal()
        await page.expect_state("agent_count", 0)


def _agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "visual-polish",
        "project_file": "/tmp/projects/sase/sase.sase",
        "status": "DONE",
        "start_time": datetime(2026, 5, 27, 12, 0, 0),
        "stop_time": datetime(2026, 5, 27, 12, 5, 0),
        "raw_suffix": "20260527120000",
        "agent_name": "visual.worker",
        "llm_provider": "codex",
        "model": "gpt-5",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _patch_dismissed_archive_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        dismissed_agents,
        "_DISMISSED_AGENTS_FILE",
        tmp_path / "dismissed_agents.json",
    )
    monkeypatch.setattr(
        dismissed_agents,
        "_DISMISSED_BUNDLES_DIR",
        tmp_path / "dismissed_bundles",
    )
    monkeypatch.setattr(
        dismissed_agents,
        "_DISMISSED_AGENT_GROUPS_DIR",
        tmp_path / "dismissed_agent_groups",
    )
    monkeypatch.setattr(
        dismissed_agents,
        "_OLD_BUNDLES_FILE",
        tmp_path / "dismissed_agent_bundles.json",
    )


def _write_done_agent_artifacts(
    *,
    project: str,
    cl_name: str,
    raw_suffix: str,
    agent_name: str,
    tribe: str,
) -> tuple[Path, Path]:
    project_dir = sase_home() / "projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{project}.sase"
    project_file.write_text("", encoding="utf-8")
    artifacts_dir = canonical_agent_artifact_path(
        project,
        "ace-run",
        raw_suffix,
        projects_root=project_dir.parent,
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "done.json").write_text(
        json.dumps(
            {
                "status": "DONE",
                "cl_name": cl_name,
                "project_file": str(project_file),
                "outcome": "completed",
                "name": agent_name,
                "model": "gpt-5",
                "llm_provider": "codex",
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": agent_name,
                "tribe": tribe,
                "model": "gpt-5",
                "llm_provider": "codex",
            }
        ),
        encoding="utf-8",
    )
    return project_file, artifacts_dir


def _patch_non_agent_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep startup deterministic without replacing the real agent loader."""

    import sase.notifications as notifications
    from sase.ace import grouping_strategy
    from sase.ace.tui.models.agent_groups import GroupingMode
    from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
    from sase.ace.tui.widgets import llm_override_indicator
    from sase.llm_provider import temporary_override

    async def _fake_axe_startup(app: AceApp) -> None:
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()

    async def _fake_axe_status_async(app: AceApp) -> None:
        app._axe_first_load_done = True

    def _fake_notification_snapshot(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            notifications=[],
            expired_ids=[],
            counts=SimpleNamespace(priority=0, rest=0, muted=0, errors=0),
        )

    monkeypatch.setattr(AceApp, "_run_axe_startup_init", _fake_axe_startup)
    monkeypatch.setattr(AceApp, "_load_axe_status_async", _fake_axe_status_async)
    monkeypatch.setattr(
        notifications,
        "read_notification_snapshot",
        _fake_notification_snapshot,
    )
    monkeypatch.setattr(
        grouping_strategy,
        "load_agent_grouping_mode",
        lambda *_args, **_kwargs: GroupingMode.STANDARD,
    )
    monkeypatch.setattr(
        grouping_strategy,
        "load_changespec_grouping_mode",
        lambda *_args, **_kwargs: ChangeSpecGroupingMode.BY_PROJECT,
    )
    monkeypatch.setattr(
        temporary_override,
        "resolve_effective_default_provider_model",
        lambda *_args, **_kwargs: ("codex", "test-model"),
    )
    monkeypatch.setattr(
        temporary_override,
        "get_active_temporary_override",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        llm_override_indicator,
        "resolve_effective_default_provider_model",
        lambda *_args, **_kwargs: ("codex", "test-model"),
    )
    monkeypatch.setattr(
        llm_override_indicator,
        "get_active_temporary_override",
        lambda *_args, **_kwargs: None,
    )


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 5.0,
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        if predicate():
            return
        if asyncio.get_event_loop().time() >= deadline:
            raise AssertionError("condition did not become true before timeout")
        await asyncio.sleep(0.02)


def _static_plain(static: Static) -> str:
    renderable = static.content
    plain = getattr(renderable, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(renderable)

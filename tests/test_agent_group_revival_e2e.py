"""Integration coverage for saved agent group save/revival."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace import dismissed_agents
from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal
from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
)
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


async def test_mark_save_preview_and_revive_saved_agent_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walk the Agents-tab m/S/R saved-group flow through preview and revive."""

    agent = _agent(
        cl_name="visual-polish",
        raw_suffix="20260527120000",
        agent_name="visual.worker",
        tag="backend",
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
        await page.press("S")
        await page.expect_state("agent_count", 0)
        await _wait_until(
            lambda: bool(dismissed_agents.list_dismissed_agent_groups().groups)
        )

        group = dismissed_agents.list_dismissed_agent_groups().groups[0]
        assert group.title == "1 agent from @backend"
        assert group.agent_count == 1

        await page.press("R")
        await page.expect_modal("SavedAgentGroupRevivalModal")
        modal = page.app.screen
        assert isinstance(modal, SavedAgentGroupRevivalModal)
        preview = modal.query_one("#saved-agent-group-preview", Static)
        assert "visual.worker" in _static_plain(preview)

        await page.press("enter")
        await page.expect_no_modal()
        await _wait_until(lambda: bool(restored))

    assert restored == [("20260527120000", None)]
    revived_group = dismissed_agents.load_dismissed_agent_group(group.group_id)
    assert revived_group is not None
    assert revived_group.times_revived == 1
    assert revived_group.agent_refs[0].raw_suffix == "20260527120000"


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
        assert "app.bulk_change_status" not in {spec.id for spec in modal._all_specs}
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("m")
        await page.press("colon")
        await page.expect_modal("CommandPaletteModal")
        modal = page.app.screen
        assert isinstance(modal, CommandPaletteModal)
        save_spec = next(
            spec for spec in modal._all_specs if spec.id == "app.bulk_change_status"
        )
        assert save_spec.label == "Bulk status / save marked agents"


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

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from sase.ace.tui.modals.episode_explorer_modal import EpisodeExplorerModal
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeImportanceFactorWire,
    EpisodeNodeWire,
    EpisodeSafetyWire,
    EpisodeSourceRefWire,
    EpisodeWeakRefsWire,
    EpisodeWire,
)
from sase.memory.episodes.inventory import query_episode_inventory
from sase.memory.episodes.storage import write_project_episode


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_episode_explorer_filters_cached_inventory_and_switches_views(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    write_project_episode(
        _episode(
            tmp_path,
            "ep-retry",
            title="Retry Feedback Episode",
            summary="Captured retry feedback for deterministic memory.",
            timestamp="2026-05-26T12:00:00Z",
            agent="planner",
            changespec="retry-cl",
            bead="sase-48.7",
            band="high",
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _episode(
            tmp_path,
            "ep-billing",
            title="Billing Cleanup Episode",
            summary="Captured billing cleanup work.",
            timestamp="2026-05-27T09:00:00Z",
            agent="coder",
            changespec="billing-cl",
            bead="sase-48.2",
            band="medium",
        ),
        projects_root=projects_root,
    )
    items = query_episode_inventory("proj", projects_root=projects_root)

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        modal = EpisodeExplorerModal(
            "proj",
            projects_root=projects_root,
            initial_items=items,
            auto_load=False,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert len(modal._visible_rows) == 2
        assert "View: overview" in _detail_text(modal)

        query_input = modal.query_one("#episode-filter-query", Input)
        query_input.value = "retry"
        await pilot.pause()

        assert [row.canonical_episode_id for row in modal._visible_rows] == ["ep-retry"]
        assert "Retry Feedback Episode" in _detail_text(modal)

        modal.action_set_view("timeline")
        assert "Planner finished" in _detail_text(modal)

        modal.action_set_view("graph")
        assert "Edge mode: strong" in _detail_text(modal)
        modal.action_toggle_edge_mode()
        assert "Edge mode: all" in _detail_text(modal)

        modal.action_set_view("sources")
        assert "Source cursor:" in _detail_text(modal)

        title = str(modal.query_one("#episode-explorer-title", Static).render())
        summary = str(
            modal.query_one("#episode-explorer-filter-summary", Static).render()
        )
        assert "Episode Explorer" in title
        assert "text=retry" in summary


async def test_episode_explorer_alias_jump_copy_open_and_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = tmp_path / "projects"
    shared_source = _source_ref(tmp_path / "shared.md", content="shared evidence\n")
    write_project_episode(
        _episode_from_sources(
            "ep-root",
            title="Canonical Episode",
            sources=[shared_source],
            timestamp="2026-05-26T12:00:00Z",
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _episode_from_sources(
            "ep-alias",
            title="Alias Episode",
            sources=[shared_source],
            timestamp="2026-05-26T12:05:00Z",
        ),
        projects_root=projects_root,
    )
    items = query_episode_inventory("proj", projects_root=projects_root)
    assert len(items) == 1
    assert [alias.alias_episode_id for alias in items[0].aliases] == ["ep-alias"]

    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.episode_explorer_modal.copy_to_system_clipboard",
        lambda text: copied.append(text) or True,
    )
    run_mock = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.modals.episode_explorer_modal.subprocess.run",
        run_mock,
    )
    monkeypatch.setenv("EDITOR", "test-editor")

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        modal = EpisodeExplorerModal(
            "proj",
            projects_root=projects_root,
            initial_items=items,
            auto_load=False,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal._filters = replace(modal._filters, status="aliases")
        modal._apply_filters_from_cache()
        assert modal._visible_rows[0].is_alias

        modal.action_jump_to_canonical()
        assert modal._visible_rows[0].canonical_episode_id == "ep-root"
        assert not modal._visible_rows[0].is_alias

        modal.action_copy_episode_id()
        assert copied == ["ep-root"]

        modal.action_open_source()
        run_mock.assert_called_once_with(
            ["test-editor", str(Path(shared_source.path))],
            check=False,
        )

        modal.action_verify_current()
        await _wait_for(lambda: modal._verify_worker is None, pilot)
        assert modal._verify_status["ep-root"].startswith("ok:")


async def test_episode_explorer_refresh_inventory_uses_thread_worker(
    tmp_path: Path,
) -> None:
    async with _TestApp().run_test(size=(100, 32)) as pilot:
        modal = EpisodeExplorerModal(
            "proj",
            projects_root=tmp_path / "projects",
            auto_load=False,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        fake_worker = SimpleNamespace(is_running=True)
        modal.run_worker = MagicMock(return_value=fake_worker)  # type: ignore[method-assign]
        modal.action_refresh_inventory()

        _, kwargs = modal.run_worker.call_args
        assert kwargs["thread"] is True
        assert kwargs["exclusive"] is True
        assert kwargs["group"] == "episode-explorer"
        assert "Loading episode inventory" in _detail_text(modal)


def _detail_text(modal: EpisodeExplorerModal) -> str:
    return str(modal.query_one("#episode-explorer-detail", Static).render())


async def _wait_for(
    predicate: Callable[[], bool],
    pilot: Any,
    *,
    attempts: int = 50,
) -> None:
    for _ in range(attempts):
        await pilot.pause()
        if predicate():
            return
    raise AssertionError("condition was not met")


def _episode(
    tmp_path: Path,
    episode_id: str,
    *,
    title: str,
    summary: str,
    timestamp: str,
    agent: str,
    changespec: str,
    bead: str,
    band: str,
) -> EpisodeWire:
    source = _source_ref(tmp_path / f"{episode_id}.md", content=f"{title}\n")
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode_id,
        project="proj",
        title=title,
        summary=summary,
        root_source_id=source.id,
        component_key=f"component/{episode_id}",
        component_root_kind="artifact",
        status="active",
        importance_score=75 if band == "high" else 45,
        importance_band=band,
        importance_factors=[
            EpisodeImportanceFactorWire(
                kind="verification_present",
                label="Verification evidence is present",
                score=12,
                evidence_ids=[source.id],
            )
        ],
        safety=EpisodeSafetyWire(warnings=["missing-source:src-missing"]),
        weak_refs=EpisodeWeakRefsWire(
            changespec_names=[changespec],
            bead_ids=[bead],
            agent_families=[agent],
            touched_paths=["src/sase/memory/episodes/render.py"],
        ),
        sources=[source],
        nodes=[
            EpisodeNodeWire(
                id=f"agent-{episode_id}",
                kind="agent_run",
                label=agent,
                source_id=source.id,
                metadata={"outcome": "completed"},
            ),
            EpisodeNodeWire(
                id=f"chat-{episode_id}",
                kind="chat",
                label=f"{episode_id}.md",
                source_id=source.id,
            ),
            EpisodeNodeWire(
                id=f"changespec-{episode_id}",
                kind="changespec",
                label=changespec,
            ),
        ],
        edges=[
            EpisodeEdgeWire(
                id=f"edge-chat-{episode_id}",
                from_node_id=f"agent-{episode_id}",
                to_node_id=f"chat-{episode_id}",
                kind="response_chat",
                evidence_ids=[source.id],
            ),
            EpisodeEdgeWire(
                id=f"edge-cl-{episode_id}",
                from_node_id=f"agent-{episode_id}",
                to_node_id=f"changespec-{episode_id}",
                kind="changespec",
            ),
        ],
        events=[
            EpisodeEventWire(
                id=f"event-{episode_id}",
                kind="agent_finish",
                title=f"{agent.title()} finished",
                timestamp=timestamp,
                evidence_ids=[source.id],
            )
        ],
        lessons=[],
        metadata={
            "agent_names": agent,
            "changespec_name": changespec,
            "bead_ids": bead,
            "outcome": "completed",
        },
    )


def _episode_from_sources(
    episode_id: str,
    *,
    title: str,
    sources: list[EpisodeSourceRefWire],
    timestamp: str,
) -> EpisodeWire:
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode_id,
        project="proj",
        title=title,
        summary=f"{title} summary.",
        root_source_id=sources[0].id,
        component_key=f"component/{episode_id}",
        component_root_kind="artifact",
        sources=sources,
        nodes=[
            EpisodeNodeWire(
                id=f"agent-{episode_id}",
                kind="agent_run",
                label="planner",
                source_id=sources[0].id,
            )
        ],
        edges=[],
        events=[
            EpisodeEventWire(
                id=f"event-{episode_id}",
                kind="agent_finish",
                title="Planner finished",
                timestamp=timestamp,
                evidence_ids=[sources[0].id],
            )
        ],
        lessons=[],
        metadata={"agent_names": "planner"},
    )


def _source_ref(path: Path, *, content: str) -> EpisodeSourceRefWire:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    data = content.encode("utf-8")
    return EpisodeSourceRefWire(
        id=f"src-{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:12]}",
        kind="chat",
        path=str(path.resolve(strict=False)),
        label=path.name,
        exists=True,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )

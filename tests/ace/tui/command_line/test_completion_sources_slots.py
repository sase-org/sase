"""Entity-slot, marked-row, and key-receipt probe tests.

Project slots merge the provider behind in-memory rows, ``cd -`` and
dotfile candidates are covered elsewhere, and the key-receipt perf probe
plus the marked-agent row on a mounted screen live here.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.sources import (
    ProviderCache,
    _in_memory_candidates,
    collect_dynamic_candidates,
    needs_provider_fetch,
)

from tests.ace.tui.command_line._completion_sources_shared import (
    await_provider_task,
    panel,
    shown,
    stub_provider,
    type_line,
)

pytest_plugins = ["tests.ace.tui.command_line._completion_sources_shared"]

__all__ = [
    "test_marked_row_for_a_variadic_agent_slot_on_the_mounted_screen",
    "test_probe_keeps_a_strong_reference_to_its_append_task",
    "test_probe_starts_at_key_receipt_not_at_the_refresh",
    "test_proc_slot_fetches_from_the_provider_when_app_state_is_empty",
    "test_project_slot_merges_provider_rows_behind_the_tui_projects",
    "test_project_slots_always_fetch_but_proc_and_agent_slots_only_when_empty",
    "test_provider_rows_merge_behind_in_memory_rows_without_duplicates",
]


def test_project_slots_always_fetch_but_proc_and_agent_slots_only_when_empty() -> None:
    """Partial in-memory readers merge the provider; complete ones stand alone."""
    app = SimpleNamespace(
        _projects=["alpha-local"],
        _agents=[SimpleNamespace(agent_name="athena.1", status="running")],
        _proc_projection=SimpleNamespace(rows=[SimpleNamespace(proc_id="proc-1")]),
    )
    assert needs_provider_fetch("project", app) is True
    assert needs_provider_fetch("project", SimpleNamespace()) is True
    assert needs_provider_fetch("proc", app) is False
    assert needs_provider_fetch("proc", SimpleNamespace()) is True
    assert needs_provider_fetch("agent", app) is False
    assert needs_provider_fetch("agent", SimpleNamespace()) is True


def test_provider_rows_merge_behind_in_memory_rows_without_duplicates() -> None:
    """In-memory project rows come first; the provider adds only what is new."""
    cache = ProviderCache(ttl_seconds=60.0)
    cache.commit(
        cache.next_generation(),
        "project",
        None,
        [
            {"value": "alpha-local", "source": "provider"},
            {"value": "zeta-remote", "source": "provider"},
            {"value": "home", "source": "provider"},
        ],
    )
    app = SimpleNamespace(_projects=["alpha-local"])
    assert [row["value"] for row in _in_memory_rows(app, "project")] == ["alpha-local"]

    merged = collect_dynamic_candidates(app, "project", None, cache)
    assert [row["value"] for row in merged] == ["alpha-local", "zeta-remote", "home"]
    assert merged[0]["source"] == "tui"


def _in_memory_rows(app: Any, kind: str) -> list[dict[str, Any]]:
    return [row.to_dynamic() for row in _in_memory_candidates(app, kind)]


async def test_proc_slot_fetches_from_the_provider_when_app_state_is_empty(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no live procs the ``proc`` slot falls back to the provider."""
    from sase.completion.candidates.protocol import Candidate

    fetched: list[str] = []

    def _fetch(kind: str) -> list[Candidate]:
        fetched.append(kind)
        return [Candidate("proc-77", "just check")]

    stub_provider(monkeypatch, _fetch)
    async with panel(grammar_handle) as (page, screen):
        assert _in_memory_candidates(page.app, "proc") == []
        await type_line(page, screen, "proc show ")
        await await_provider_task(screen)
        assert fetched == ["proc"]
        assert "proc-77" in shown(screen)


async def test_project_slot_merges_provider_rows_behind_the_tui_projects(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project no loaded agent mentions still completes through the provider."""
    from sase.completion.candidates.protocol import Candidate

    fetched: list[str] = []

    def _fetch(kind: str) -> list[Candidate]:
        fetched.append(kind)
        return [Candidate("zeta-remote", "enabled"), Candidate("home", "enabled")]

    stub_provider(monkeypatch, _fetch)
    async with panel(grammar_handle) as (page, screen):
        monkeypatch.setattr(page.app, "_projects", ["alpha-local"], raising=False)
        assert [row.value for row in _in_memory_candidates(page.app, "project")] == [
            "alpha-local"
        ]
        await type_line(page, screen, "project disable ")
        await await_provider_task(screen)
        assert fetched == ["project"]
        assert {"alpha-local", "zeta-remote", "home"} <= set(shown(screen))


async def test_marked_row_for_a_variadic_agent_slot_on_the_mounted_screen(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``agent wait `` offers ``‹N marked›`` built from the Agents-tab mark order."""
    from tests.ace.tui._agent_marking_helpers import _make_agent

    alpha = _make_agent(
        cl_name="alpha", agent_name="alpha", raw_suffix="20240101120000"
    )
    beta = _make_agent(cl_name="beta", agent_name="beta", raw_suffix="20240101130000")
    idle = _make_agent(cl_name="idle", agent_name="idle", raw_suffix="20240101140000")
    async with panel(grammar_handle) as (page, screen):
        app = page.app
        monkeypatch.setattr(app, "_agents", [alpha, beta, idle])
        monkeypatch.setattr(app, "_agents_with_children", [alpha, beta, idle])
        monkeypatch.setattr(app, "_marked_agent_order", [beta.identity, alpha.identity])
        await type_line(page, screen, "agent wait ")

        first = screen._popup_state.items[0]
        assert first["display"] == "‹2 marked›"
        assert first["insert_text"] == "beta alpha "
        assert {"alpha", "beta", "idle"} <= set(shown(screen))

        await type_line(
            page, screen, "agent show "
        )  # a single-value slot: no marked row
        assert not any("marked" in text for text in shown(screen))


async def test_probe_keeps_a_strong_reference_to_its_append_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop holds tasks weakly, so the probe must hold its own until done."""
    from sase.ace.tui.command_line import completion_probe

    path = tmp_path / "perf.jsonl"
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(path))

    completion_probe.schedule_command_line_keystroke_probe(
        lambda callback: callback(), time.perf_counter(), True
    )
    pending = set(completion_probe._PENDING_APPENDS)
    assert len(pending) == 1
    await asyncio.gather(*pending)
    await asyncio.sleep(0)
    assert not completion_probe._PENDING_APPENDS
    assert json.loads(path.read_text(encoding="utf-8"))["indexed"] is True


async def test_probe_starts_at_key_receipt_not_at_the_refresh(
    grammar_handle: Any,
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample includes the Key -> ``TextArea.Changed`` queue delay."""
    from sase.ace.tui.command_line.input import CommandLineInput

    perf_path = tmp_path / "perf.jsonl"
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(perf_path))

    def _samples() -> list[dict[str, Any]]:
        if not perf_path.exists():
            return []
        return [
            json.loads(line)
            for line in perf_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    async with panel(grammar_handle) as (page, screen):
        refresh_entries: list[float] = []
        real_refresh = screen._refresh_completion

        def _spy_refresh() -> None:
            refresh_entries.append(time.perf_counter())
            real_refresh()

        monkeypatch.setattr(screen, "_refresh_completion", _spy_refresh)
        sent_at = time.perf_counter()
        await page.press("b")
        await page.wait_for(
            lambda _state: any(s["t_keypress"] >= sent_at for s in _samples())
        )
        sample = next(s for s in _samples() if s["t_keypress"] >= sent_at)
        assert sample["action"] == "command_line.complete"
        assert refresh_entries
        assert sent_at <= sample["t_keypress"] < refresh_entries[0]

        widget = screen.query_one(CommandLineInput)
        # A refresh that finds the text the key arrived with was not that key's.
        widget._keypress_stamp = (1.0, widget.text)
        assert widget.take_keypress_stamp() is None
        widget._keypress_stamp = (2.0, widget.text + "x")
        assert widget.take_keypress_stamp() == 2.0
        assert widget.take_keypress_stamp() is None

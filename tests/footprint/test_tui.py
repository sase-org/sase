"""Tests for the Footprint TUI recorder: seams, flush thread, and budgets."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

import pytest

from sase.footprint import _tui, ids
from sase.ace.tui._app_watchers import _BUILTIN_MODES
from sase.footprint.catalog import load_catalog
from sase.footprint.paths import generation_path, spool_dir


@pytest.fixture()
def footprint_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Isolate Footprint state and reset the TUI counter module."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_FOOTPRINT", "test")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path))
    _tui._reset_for_tests()
    try:
        yield tmp_path
    finally:
        _tui._reset_for_tests()


def _today_lines(home: Path) -> list[str]:
    from datetime import date

    path = spool_dir() / f"{date.today().isoformat()}.jsonl"
    if not path.exists():
        return []
    return path.read_text(encoding="ascii").splitlines()


def _counts() -> dict[tuple[str, str], int]:
    with _tui._LOCK:
        return dict(_tui._COUNTS)


# ---------------------------------------------------------------------------
# Unit: aggregation and the spool write
# ---------------------------------------------------------------------------


def test_flush_now_writes_aggregated_lines_and_probe(
    footprint_home: Path,
) -> None:
    _tui.bump("tui:app.dismiss_toasts", "key")
    _tui.bump("tui:app.dismiss_toasts", "key")
    _tui.bump("tui:fold.cycle_hooks", "mode")
    _tui.flush_now()

    lines = _today_lines(footprint_home)
    assert len(lines) == 3
    rows = [json.loads(line) for line in lines]
    by_feature = {(row["f"], row["v"]): row for row in rows if "f" in row}
    assert by_feature[("tui:app.dismiss_toasts", "key")]["n"] == 2
    assert by_feature[("tui:fold.cycle_hooks", "mode")]["n"] == 1
    assert by_feature[("tui:app.dismiss_toasts", "key")]["o"] == "ok"
    probes = [row for row in rows if row.get("probe") == "tui"]
    assert len(probes) == 1
    assert all(len(line.encode("ascii")) <= 512 for line in lines)


def test_bump_performs_no_os_write(
    footprint_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_write(fd: int, payload: bytes) -> int:
        raise AssertionError("bump() must not perform event-loop I/O")

    monkeypatch.setattr(os, "write", fail_write)
    for _ in range(500):
        _tui.bump("tui:app.dismiss_toasts", "key")
    assert _counts() == {("tui:app.dismiss_toasts", "key"): 500}


def test_all_spool_io_happens_off_the_loop_thread(
    footprint_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write
    calls: list[tuple[str, bytes]] = []

    def record_write(fd: int, payload: bytes) -> int:
        if payload.startswith(b'{"s":1'):
            calls.append((threading.current_thread().name, payload))
        return real_write(fd, payload)

    monkeypatch.setattr(os, "write", record_write)
    monkeypatch.setattr(_tui, "FLUSH_INTERVAL_S", 0.05)
    _tui.bump("tui:app.dismiss_toasts", "key")

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not _today_lines(footprint_home):
        time.sleep(0.05)  # sase-test-wait: poll daemon flusher thread for spool write
    assert _today_lines(footprint_home), "daemon flusher never wrote"
    assert calls, "no Footprint os.write calls observed"
    assert all(name == _tui.FLUSH_THREAD_NAME for name, _ in calls)


def test_bump_microbench_stays_within_two_microseconds(
    footprint_home: Path,
) -> None:
    # Warm the lazy flusher and hot call path before timing the steady-state
    # bump cost. Keep that state through measurement so every batch measures
    # the same path the TUI uses after its first action.
    for _ in range(200):
        _tui.bump("tui:app.dismiss_toasts", "key")
    # Min-of-batches: the shared host is noisy, so the quietest batch is
    # the honest measure of bump's own cost.
    iterations = 5000
    best = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        for _ in range(iterations):
            _tui.bump("tui:app.dismiss_toasts", "key")
        best = min(best, (time.perf_counter() - start) / iterations)
    assert best <= 2e-6, f"best bump cost {best * 1e6:.3f} µs"


def test_mode_off_discards_counts(
    footprint_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tui.bump("tui:app.dismiss_toasts", "key")
    monkeypatch.setattr(_tui, "effective_mode", lambda: "off")
    _tui.flush_now()
    assert _today_lines(footprint_home) == []


def test_generation_change_discards_counts(
    footprint_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_tui, "_ensure_flusher", lambda: None)
    _tui._START_GENERATION = "rev-a"
    _tui._GENERATION_LOADED = True
    generation_path().parent.mkdir(parents=True, exist_ok=True)
    generation_path().write_text("rev-b\n", encoding="ascii")
    _tui.bump("tui:app.dismiss_toasts", "key")
    _tui.flush_now()
    assert _today_lines(footprint_home) == []
    assert _counts() == {}

    generation_path().write_text("rev-b\n", encoding="ascii")
    _tui._START_GENERATION = "rev-b"
    _tui.bump("tui:app.dismiss_toasts", "key")
    _tui.flush_now()
    assert len(_today_lines(footprint_home)) == 2


def test_navigation_chrome_is_never_counted(footprint_home: Path) -> None:
    sample = next(iter(ids.NAVIGATION_ACTIONS))
    _tui.bump(sample, "key")
    _tui.flush_now()
    assert _today_lines(footprint_home) == []
    assert _counts() == {}


def test_invalid_id_collapses_to_other(footprint_home: Path) -> None:
    _tui.bump("tui:Has Spaces!!", "key")
    _tui.bump("bogus-no-colon", "key")
    _tui.flush_now()
    rows = [json.loads(line) for line in _today_lines(footprint_home)]
    features = {row["f"] for row in rows if "f" in row}
    assert features == {"tui:~other"}


# ---------------------------------------------------------------------------
# Catalog agreement: one ID per keymap scope and builtin mode
# ---------------------------------------------------------------------------


def test_every_keymap_scope_has_a_catalogued_action() -> None:
    from sase.ace.tui.keymaps.types import KeymapRegistry

    _, entries = load_catalog()
    catalogued = {entry.id for entry in entries}
    scopes = [
        field.name
        for field in dataclass_fields(KeymapRegistry)
        if field.name not in ("modes", "legacy_card_block_brackets")
    ]
    assert scopes, "expected at least one keymap scope"
    for scope in scopes:
        scope_cls = _scope_dataclass(scope)
        for field in dataclass_fields(scope_cls):
            feature_id = ids.tui_id(scope, field.name)
            if feature_id in ids.NAVIGATION_ACTIONS:
                continue
            assert feature_id in catalogued, f"{feature_id} missing from catalog"


def _scope_dataclass(scope: str) -> Any:
    from sase.ace.tui.keymaps import types as keymap_types

    names = {
        "app": "AppKeymaps",
        "command_line": "CommandLineKeymaps",
        "config": "ConfigHubKeymaps",
        "statistics": "StatisticsPaneKeymaps",
        "gate": "GateModalKeymaps",
        "machines": "MachinesPaneKeymaps",
        "memory": "MemoryPanelKeymaps",
        "snippets": "SnippetPanelKeymaps",
        "projects": "ProjectsPaneKeymaps",
        "tool_runs": "ToolRunsPaneKeymaps",
    }
    return getattr(keymap_types, names[scope])


def test_builtin_mode_keys_are_catalogued() -> None:
    from sase.ace.tui.keymaps.mode_keymaps import _BUILTIN_MODE_CLASSES
    from sase.ace.tui._app_watchers import _flatten

    _, entries = load_catalog()
    catalogued = {entry.id for entry in entries}
    for mode_name, cls in sorted(_BUILTIN_MODE_CLASSES.items()):
        short = mode_name[: -len("_mode")] if mode_name.endswith("_mode") else mode_name
        flat: dict[str, str] = {}
        _flatten(dict(cls().keys), short, flat)
        assert flat, f"{mode_name} has no keys"
        for dotted in sorted(set(flat.values())):
            assert f"tui:{dotted}" in catalogued, f"tui:{dotted} missing"


# ---------------------------------------------------------------------------
# Textual contract: every seam records exactly one hit
# ---------------------------------------------------------------------------


async def test_tui_contract_pilot_records_each_seam_once(
    footprint_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import textual

    assert textual.__version__ == "8.0.1", (
        f"contract ran on Textual {textual.__version__}, pinned is 8.0.1"
    )
    monkeypatch.setenv("SASE_FOOTPRINT", "test")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(footprint_home))

    from textual.events import Key

    from sase.ace.testing import AcePage
    from sase.ace.tui.commands.execute import execute_command
    from sase.ace.tui.commands.types import CommandExecutor, CommandSpec
    from sase.ace.tui.modals.help_modal.modal import HelpModal

    async with AcePage(initial_tab="artifacts") as page:
        app = page.app
        await page.pause()
        assert ("view:tab.artifacts", "key") not in _counts(), (
            "the restored startup tab must not be counted"
        )
        _tui._reset_for_tests()

        def delta() -> dict[tuple[str, str], int]:
            return _counts()

        # 1. run_action seam: one app-scope binding.
        assert await app.run_action("dismiss_toasts") is True
        assert delta() == {("tui:app.dismiss_toasts", "key"): 1}, delta()
        _tui._reset_for_tests()

        # 2. palette seam: one palette execution.
        spec = CommandSpec(
            id="app.dismiss_toasts",
            label="Dismiss toasts",
            key_sequence=("Z",),
            key_display="Z",
            category="Navigation",
            tabs=("artifacts", "agents", "services"),
            executor=CommandExecutor(kind="app_action", action="dismiss_toasts"),
        )
        execute_command(app, spec)
        assert delta() == {("tui:app.dismiss_toasts", "palette"): 1}, delta()
        _tui._reset_for_tests()

        # 3. prefix-mode seam: one fold sub-key.
        fold_key = str(app._keymap_registry.fold_mode.keys["cycle_stitches"])
        app._fold_mode_active = True
        app.on_key(Key(fold_key, fold_key))
        assert delta() == {("tui:fold.cycle_stitches", "mode"): 1}, delta()
        _tui._reset_for_tests()

        # 4. view-entry seam: one tab switch.
        app.current_tab = "agents"
        await page.pause()
        assert delta() == {("view:tab.agents", "key"): 1}, delta()
        _tui._reset_for_tests()

        # 5. modal seam: one pushed modal.
        app.push_screen(HelpModal("agents", registry=app._keymap_registry))
        await page.pause()
        assert delta() == {("view:modal.help", "key"): 1}, delta()
        app.pop_screen()
        await page.pause()


def test_builtin_modes_covered_by_seam() -> None:
    assert set(_BUILTIN_MODES) == {
        "fold",
        "copy",
        "leader",
        "bang",
        "bead_issue",
    }

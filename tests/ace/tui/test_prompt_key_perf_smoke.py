"""Non-slow smoke test for the prompt-key perf harness (epic sase-1ex).

Runs the smallest case end to end -- one ``<space>`` plus one ``ctrl+p`` --
and asserts that samples were recorded, so the harness cannot rot. The slow
bench in ``bench_prompt_bar_keys.py`` carries the full matrix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from collections.abc import Callable

from textual.app import App, ComposeResult

from sase.ace.tui.app import AceApp
from sase.ace.tui.util.perf import JKPerfTimer
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui._bench_tui_jk_helpers import (
    _perf_jsonl as _perf_jsonl,
    _read_samples,
    _wait_for_startup,
)
from tests.conftest import redirect_sase_home

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)


async def _settle_startup(app: AceApp, pilot: object) -> None:
    """Wait for startup, tolerating the pre-existing scan-wire mismatch.

    The installed binding can emit an agent-scan wire schema the checkout
    no longer accepts, which leaves the agents first-load flag unset. The
    prompt bar mounts independently of that worker, so proceed anyway.
    """
    try:
        await _wait_for_startup(app, pilot)
    except AssertionError:
        await pilot.pause()  # type: ignore[attr-defined]


async def _await_bar_mounted(app: AceApp, pilot: object) -> PromptInputBar:
    """Wait until the home prompt bar finishes mounting."""
    import asyncio

    deadline = asyncio.get_running_loop().time() + 15.0
    while True:
        try:
            bar = app.query_one(PromptInputBar)
        except Exception:  # noqa: BLE001 - bar not present yet.
            bar = None
        if bar is not None and bar.is_mounted:
            return bar
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("prompt bar did not mount within 15s")
        await pilot.pause()  # type: ignore[attr-defined]


async def test_prompt_key_perf_harness_records_space_and_cycle(
    _perf_jsonl: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One ``<space>`` and one ``ctrl+p`` each record a key-to-paint sample."""
    from tests.ace.tui.bench_prompt_bar_keys import (
        _stub_agent_scan_backend,
        _stub_agent_tab_catalog_compat,
        _stub_jinja_compat,
    )

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _stub_agent_scan_backend(monkeypatch, tmp_path / ".sase" / "projects")
    _stub_agent_tab_catalog_compat(monkeypatch)
    _stub_jinja_compat(monkeypatch)
    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs",
        lambda *args, **kwargs: [
            ("#git:foo", "#git:foo"),
            ("#git:bar", "#git:bar"),
        ],
    )
    monkeypatch.setattr(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru",
        lambda *args, **kwargs: ["#git:foo", "#git:bar"],
    )
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)
        app.action_start_agent_from_patch()
        await _await_bar_mounted(app, pilot)
        # Phase mru-snapshot serves cycle keys from the app snapshot, not
        # the loader: seed it ready so this press exercises the cycle path
        # deterministically instead of racing the startup warm build.
        from sase.ace.tui.launchable_mru import LaunchableMruSnapshot

        app._launchable_mru_snapshot = LaunchableMruSnapshot(
            state="ready",
            pairs=(("#git:foo", "#git:foo"), ("#git:bar", "#git:bar")),
        )
        await pilot.press("ctrl+p")
        await pilot.pause()

    actions = [s.get("action") for s in _read_samples(_perf_jsonl)]
    assert "prompt_space" in actions
    assert "prompt_cycle_ctrl_p" in actions


def test_prompt_key_perf_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``SASE_TUI_PERF=1`` the app holds no timer (true no-op)."""
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    monkeypatch.delenv("SASE_TUI_PERF_PATH", raising=False)
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    assert app._jk_perf is None


class _BareCycleApp(App):
    """Minimal host for the cycle-key perf path (no agents scan)."""

    ENABLE_COMMAND_PALETTE = False

    _jk_perf: JKPerfTimer | None
    _jk_perf_begin: Callable[[str], None]

    def compose(self) -> ComposeResult:
        yield PromptTextArea()


async def test_prompt_cycle_key_records_perf_sample(
    _perf_jsonl: Path,
) -> None:
    """``ctrl+p`` on a bare host records a cycle sample through the timer."""
    from unittest.mock import patch

    app = _BareCycleApp()
    app._jk_perf = JKPerfTimer()
    app._jk_perf_begin = lambda action: app._jk_perf.begin(action, "agents")  # type: ignore[union-attr]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#git:foo ")
        ta.move_cursor(ta._location_from_absolute(len("#git:foo ")))
        ta.focus()
        with patch(
            "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru",
            return_value=["#git:foo", "#git:bar"],
        ):
            await pilot.press("ctrl+p")
            await pilot.pause()

    assert app._jk_perf is not None
    samples = app._jk_perf.samples()
    assert [s["action"] for s in samples] == ["prompt_cycle_ctrl_p"]
    assert samples[0]["tab"] == "agents"
    assert samples[0]["paint_ms"] >= samples[0]["model_ms"] >= 0.0
    assert _read_samples(_perf_jsonl), "cycle sample missing from JSONL"


def test_prompt_key_io_probe_counts_main_thread_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The I/O probe counts each signal once and ignores other threads."""
    import json
    import subprocess
    import threading

    from sase.ace.tui.util.fs_watcher import ArtifactWatcher
    from tests.ace.tui._prompt_key_io_probes import prompt_key_io_probe

    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()

    import sase.history.vcs_macro_mru as mru_module
    import sase.core.project_lifecycle_facade as facade_module
    from sase.legacy_xprompt_names import VCS_MACRO_MRU_FILENAME

    with prompt_key_io_probe() as probe:
        assert mru_module._load_vcs_macro_mru() == []
        mru_module._save_vcs_macro_mru(["#git:foo"])
        assert json.loads((home / VCS_MACRO_MRU_FILENAME).read_text()) == {
            "entries": ["#git:foo"]
        }
        assert mru_module._load_vcs_macro_mru() == ["#git:foo"]
        assert facade_module.list_project_records(home / "projects", ["enabled"]) == []
        io_proc = subprocess.Popen(["true"])
        assert io_proc.wait(timeout=30) == 0
        worker = threading.Thread(target=lambda: None)
        worker.start()
        worker.join(timeout=30)
        watcher = ArtifactWatcher(
            paths=[watch_dir],
            on_change=lambda: None,
            schedule_callback=lambda cb: cb(),
        )
        assert watcher.start() is True
        watcher.stop()
        # Off-thread calls never count.
        probe_thread = threading.Thread(
            target=lambda: (
                mru_module._load_vcs_macro_mru(),
                subprocess.Popen(["true"]).wait(timeout=30),
            )
        )
        probe_thread.start()
        probe_thread.join(timeout=30)

    assert probe.mru_reads == 2
    assert probe.mru_writes == 1
    assert probe.list_project_records == 1
    # One explicit ``true`` plus, on the first watcher start per process,
    # the ``ldconfig`` spawn inside ``ctypes.util.find_library`` (a
    # process-global cache, so other tests may have warmed it already).
    assert probe.popen in (1, 2)
    assert probe.watcher_start == 1
    assert probe.watcher_stop == 1
    assert probe.thread_join >= 1
    assert probe.total > 0
    assert set(probe.nonzero()) == {
        "mru_reads",
        "mru_writes",
        "list_project_records",
        "popen",
        "watcher_start",
        "watcher_stop",
        "thread_join",
    }

    with prompt_key_io_probe() as quiet:
        pass
    quiet.assert_quiet()

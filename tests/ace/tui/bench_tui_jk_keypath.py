"""Agents-tab j/k keypath subprocess and provider-discovery regression gate."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui import artifact_tabs
from sase.ace.tui.app import AceApp
from tests.ace.tui._bench_tui_jk_helpers import (
    _KEYS_PER_SCENARIO,
    _install_agents_fixture,
    _perf_jsonl as _perf_jsonl,
    _wait_for_startup,
)

pytestmark = pytest.mark.slow


async def test_bench_keystroke_reaches_no_provider_discovery_or_subprocess(
    _perf_jsonl: Path,
) -> None:
    """Regression gate for the `keypath` phase (``bead:sase-uv.1``).

    Today, every key press on the Agents tab reaches ``on_key`` ->
    ``_handle_link_prefix_key`` -> ``_link_follow_available`` ->
    ``link_edges_for_selection`` -> ``selected_link_subject`` ->
    ``_subject_from_agents`` -> ``accent_and_icon_for_ref`` ->
    ``descriptor_for_artifacts_pane_id`` -> ``resolve_artifacts_subtabs``,
    which can fork a git subprocess on a provider-discovery cache miss
    (``tui_perf.md`` rules 8 and 11; see the research report linked from
    ``plans/202608/ace_tui_responsiveness.md``). This is a behavioural
    assertion, not a timing one, so it cannot flake -- and it is expected to
    fail until `keypath` resolves fixed panes (Agents included) straight
    from the static ``ARTIFACTS_ACCENTS``/``ARTIFACTS_ICONS`` tables instead
    of routing through discovery.

    ``_link_follow_available`` swallows any exception raised inside it
    (``except Exception: return False``), so this spies on
    ``resolve_artifacts_subtabs`` and counts calls rather than raising --
    counting survives that swallow, a raise would not.

    Both assertions are scoped to the event-loop thread. ``tui_perf.md`` rule
    1 *prescribes* pushing subprocess and disk work off the loop
    (``to_thread`` / ``run_worker(thread=True)``), and rule 11 governs the
    keystroke path itself, so a fork from a Textual worker thread -- the
    update-status poller, the detail-header enrichment worker -- is the
    compliant design, not the regression this gate exists to catch. Counting
    every subprocess in the process would fail on unrelated background work
    and make this gate flaky by construction, which is exactly what its
    "behavioural, so it cannot flake" contract rules out. Off-loop calls are
    still collected and printed, so the diagnostic is not lost.
    """
    loop_thread = threading.current_thread()
    discovery_calls: list[None] = []
    background_calls: list[str] = []
    real_resolve = artifact_tabs.resolve_artifacts_subtabs

    def _spy_resolve() -> tuple[object, ...]:
        if threading.current_thread() is loop_thread:
            discovery_calls.append(None)
        return real_resolve()

    subprocess_calls: list[str] = []

    def _guard_subprocess(*args: object, **kwargs: object) -> None:
        # argv only: ``kwargs`` carries the inherited ``env``, and rendering
        # it into an assertion message leaks the whole environment (API keys
        # and tokens included) into pytest output and CI logs.
        argv = args[0] if args else kwargs.get("args")
        thread = threading.current_thread()
        if thread is not loop_thread:
            background_calls.append(f"{thread.name}: {argv!r}")
            raise AssertionError("background subprocess suppressed by this bench")
        subprocess_calls.append(repr(argv))
        raise AssertionError("a keystroke spawned a subprocess")

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_agents_fixture(app)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()

        with (
            patch.object(artifact_tabs, "resolve_artifacts_subtabs", _spy_resolve),
            patch.object(subprocess, "run", side_effect=_guard_subprocess),
            patch.object(subprocess, "Popen", side_effect=_guard_subprocess),
        ):
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.01)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("k")
                await pilot.pause(0.01)

    if background_calls:
        print("off-loop subprocesses during the run (rule 1 compliant):")
        for call in background_calls:
            print(f"  {call}")
    assert not discovery_calls, (
        f"{len(discovery_calls)} of {_KEYS_PER_SCENARIO * 2} keystroke(s) reached "
        "resolve_artifacts_subtabs() on the event loop; keypath must resolve "
        "fixed panes from the static accent/icon tables instead of provider "
        "discovery"
    )
    assert not subprocess_calls, (
        f"a keystroke forked a subprocess on the event loop: {subprocess_calls}"
    )
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    assert not stall_path.exists() or not stall_path.read_text().strip()

"""Prompt ``<space>`` / ``<ctrl+n/p>`` key-to-paint benchmark (epic sase-1ex).

Phase key-perf-harness baseline. Drives sase's TUI through ``Pilot`` with
``SASE_TUI_PERF=1`` enabled, captures key-to-paint samples to a JSONL file,
and prints one p50/p95/max table per case. Marked ``slow`` so it does not
run as part of the default suite -- run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_prompt_bar_keys.py

The fixture is an isolated SASE home holding about 30 MRU entries spanning
five launchable projects (canonical plus display spellings), Patch refs, one
stale entry for each of the four prune classes, and padding. Provider
detection runs through the production call shape (a per-entry fake rooted at
the fixture projects keeps the bench hermetic).

No budgets are asserted: shared-host timing is noisy. Later sase-1ex phases
rerun the relevant cases and record before/after numbers in their bead
notes.
"""

from __future__ import annotations

import statistics
import sys
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.workspace_provider import get_ref_patterns
from tests.ace.tui._bench_tui_jk_helpers import (
    _perf_jsonl as _perf_jsonl,
    _read_samples,
    _wait_for_startup,
)
from tests.conftest import redirect_sase_home

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_LAUNCHABLE: tuple[tuple[str, str], ...] = (
    ("proj_alpha", "alpha"),
    ("proj_beta", "beta"),
    ("proj_gamma", "gamma"),
    ("proj_delta", "delta"),
    ("proj_echo", "echo"),
)
_STALE_PROJECT_KEY = "proj_stale"
_PATCH_NAMES = ("bench-patch-01", "bench-patch-02", "bench-patch-03")
_STEADY_SPACE_ROUNDS = 10
_BURST_KEYS = 6
_BURST_CADENCE_S = 0.05


def _write_project(home: Path, key: str, display: str, workspace: Path) -> None:
    project_dir = home / "projects" / key
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{key}.sase").write_text(
        f"PROJECT_NAME: {display}\nWORKSPACE_DIR: {workspace}\nNAME: {key}_c\n",
        encoding="utf-8",
    )


def _seed_prompt_key_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
    """Build the isolated home and keep global-state reads hermetic."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir(parents=True, exist_ok=True)

    for key, display in _LAUNCHABLE:
        workspace = workspace_root / key
        workspace.mkdir(exist_ok=True)
        _write_project(sase_home, key, display, workspace)
    # Stale-known project: the spec file exists but its workspace does not,
    # so the launchability check drops it while the record still resolves.
    _write_project(
        sase_home,
        _STALE_PROJECT_KEY,
        "stale",
        workspace_root / "does-not-exist",
    )

    entries: list[str] = []
    for key, _display in _LAUNCHABLE:
        entries.append(f"#git:{key}")
    # Display/alias spellings of the same projects.
    entries.extend(["#git:alpha", "#git:beta", "+gamma"])
    for name in _PATCH_NAMES:
        entries.append(f"#gh:{name}")
    # One stale entry per prune class: default, stale-known, gone, and
    # provider-mismatched (the last only when a ``gh`` ref pattern exists).
    entries.append("#git:home")
    entries.append(f"#git:{_STALE_PROJECT_KEY}")
    entries.append("#git:vanished_xyz")
    mismatch_supported = "gh" in get_ref_patterns()
    if mismatch_supported:
        entries.append("#git:proj_alpha".replace("#git:", "#gh:", 1))
    while len(entries) < 30:
        entries.append(f"#git:vanished_pad_{len(entries):02d}")
    import json

    (sase_home / "vcs_xprompt_mru.json").write_text(
        json.dumps({"entries": entries[:30]}), encoding="utf-8"
    )

    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *args, **kwargs: [SimpleNamespace(name=name) for name in _PATCH_NAMES],
    )

    import sase.workspace_provider as provider_module

    real_detect = provider_module.detect_workflow_type

    def _fixture_detect(project_file: str) -> str:
        if _STALE_PROJECT_KEY in project_file or "/projects/proj_" in project_file:
            return "git"
        return real_detect(project_file)

    monkeypatch.setattr(provider_module, "detect_workflow_type", _fixture_detect)
    import sase.ace.tui.modals.project_discovery as discovery_module

    monkeypatch.setattr(discovery_module, "detect_workflow_type", _fixture_detect)
    return {"sase_home": sase_home, "mismatch_supported": mismatch_supported}


def _stats(vals: list[float]) -> dict[str, float]:
    ordered = sorted(vals)
    n = len(ordered)
    p95_idx = max(0, int(round(0.95 * (n - 1))))
    return {
        "n": float(n),
        "p50": float(statistics.median(ordered)),
        "p95": ordered[p95_idx],
        "max": ordered[-1],
    }


def _print_prompt_table(
    title: str, rows: list[tuple[str, list[dict[str, object]]]]
) -> None:
    print(f"\n{title}", file=sys.stderr)
    print(
        f"  {'case':<18} {'n':>3} {'paint_p50':>9} {'paint_p95':>9} "
        f"{'paint_max':>9} {'hdl_p50':>7} {'hdl_p95':>7} {'hdl_max':>7}",
        file=sys.stderr,
    )
    for case, samples in rows:
        paint = _stats([float(s["paint_ms"]) for s in samples])  # type: ignore[arg-type]
        handler = _stats([float(s["model_ms"]) for s in samples])  # type: ignore[arg-type]
        print(
            f"  {case:<18} {int(paint['n']):>3d} "
            f"{paint['p50']:>9.2f} {paint['p95']:>9.2f} {paint['max']:>9.2f} "
            f"{handler['p50']:>7.2f} {handler['p95']:>7.2f} "
            f"{handler['max']:>7.2f}",
            file=sys.stderr,
        )


def _stub_agent_scan_backend(
    monkeypatch: pytest.MonkeyPatch, projects_root: Path
) -> None:
    """Replace the agents-scan backend with a valid empty snapshot.

    The installed ``sase_core_rs`` wheel can lag the checkout's scan-wire
    schema, which fails the startup agents worker. The prompt keys under
    measurement never read the agents list, so an empty snapshot keeps the
    harness hermetic without touching the measured paths.
    """
    from sase.core.agent_scan_facade import agent_scan_wire_from_dict

    empty = agent_scan_wire_from_dict(
        {"schema_version": 10, "projects_root": str(projects_root)}
    )
    import sase.ace.tui.models.agent_loader as loader_module

    monkeypatch.setattr(
        loader_module, "scan_agent_artifacts", lambda *args, **kwargs: empty
    )
    monkeypatch.setattr(
        loader_module, "scan_agent_artifact_dirs", lambda *args, **kwargs: empty
    )


def _stub_agent_tab_catalog_compat(monkeypatch: pytest.MonkeyPatch) -> bool:
    """Stub the tab-catalog binding, but only when the wheel lacks it.

    Returns whether the stub was installed. Healthy environments keep the
    production binding; stale wheels get an empty catalog, which is exact
    here because the scan stub above always leaves the roster empty.
    """
    from types import SimpleNamespace

    from sase.core import rust as rust_module

    try:
        rust_module.require_rust_binding("build_agent_tab_catalog")
    except AttributeError:
        pass
    else:
        return False

    import sase.ace.tui.models.agent_tab_index as tab_index

    def _empty_catalog(roots: Iterable[Any], **kwargs: Any) -> Any:
        root_list = list(roots)
        if root_list:
            raise AssertionError(
                "compat tab-catalog stub cannot index a non-empty roster"
            )
        return SimpleNamespace(keys=(), entries=())

    monkeypatch.setattr(tab_index, "build_agent_tab_catalog", _empty_catalog)
    return True


def _stub_jinja_compat(monkeypatch: pytest.MonkeyPatch) -> bool:
    """Stub Jinja scope variables, but only when the wheel lacks them.

    Returns whether the stub was installed. The empty shape is exact for
    the bench texts, which carry no template variables, so the
    unknown-variable lint simply finds nothing.
    """
    from sase.core import rust as rust_module

    try:
        rust_module.require_rust_binding("jinja_scope_variables")
    except AttributeError:
        pass
    else:
        return False

    import sase.macro.jinja_assist as jinja_assist

    def _empty_scope_variables(text: object, scope: object) -> object:
        return jinja_assist._scope_variables_from_dict({})

    monkeypatch.setattr(jinja_assist, "jinja_scope_variables", _empty_scope_variables)
    return True


async def _settle_startup(app: AceApp, pilot: object) -> None:
    """Wait for startup, tolerating the pre-existing scan-wire mismatch.

    The installed binding can emit an agent-scan wire schema the checkout
    no longer accepts, which leaves the agents first-load flag unset. The
    prompt bar mounts independently of that worker, so the bench proceeds
    anyway and notes it.
    """
    try:
        await _wait_for_startup(app, pilot)
    except AssertionError:
        print(
            "note: ACE startup did not fully settle; "
            "continuing without steady-state startup",
            file=sys.stderr,
        )
        await pilot.pause()  # type: ignore[attr-defined]


def _stall_row_count(perf_path: Path) -> int:
    stall_path = perf_path.with_name("tui_stalls.jsonl")
    if not stall_path.exists():
        return 0
    return len([line for line in stall_path.read_text().splitlines() if line.strip()])


async def _open_space_bar(app: AceApp, pilot: object) -> PromptInputBar:
    """Open the home prompt bar and wait until it finishes mounting."""
    import asyncio

    app.action_start_agent_from_patch()
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


async def _await_no_bar(app: AceApp, pilot: object) -> None:
    """Wait until the previous prompt bar fully detaches."""
    import asyncio

    deadline = asyncio.get_running_loop().time() + 15.0
    while True:
        try:
            app.query_one(PromptInputBar)
        except Exception:  # noqa: BLE001 - no bar mounted.
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("prompt bar did not detach within 15s")
        await pilot.pause()  # type: ignore[attr-defined]


async def test_bench_prompt_bar_keys(
    _perf_jsonl: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Record the key-perf-harness baseline table for the prompt keys."""
    seed = _seed_prompt_key_home(monkeypatch, tmp_path)
    _stub_agent_scan_backend(monkeypatch, Path(str(seed["sase_home"])) / "projects")
    _stub_agent_tab_catalog_compat(monkeypatch)
    _stub_jinja_compat(monkeypatch)
    rows: list[tuple[str, list[dict[str, object]]]] = []

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _settle_startup(app, pilot)

        before = len(_read_samples(_perf_jsonl))
        await _open_space_bar(app, pilot)
        await pilot.pause()
        first_space = [
            s
            for s in _read_samples(_perf_jsonl)[before:]
            if s.get("action") == "prompt_space"
        ]
        assert first_space, "first <space> recorded no prompt_space sample"
        rows.append(("first_space", first_space))

        steady: list[dict[str, object]] = []
        for _ in range(_STEADY_SPACE_ROUNDS):
            app._unmount_prompt_bar()
            await _await_no_bar(app, pilot)
            before = len(_read_samples(_perf_jsonl))
            await _open_space_bar(app, pilot)
            await pilot.pause()
            steady.extend(
                s
                for s in _read_samples(_perf_jsonl)[before:]
                if s.get("action") == "prompt_space"
            )
        assert len(steady) == _STEADY_SPACE_ROUNDS, (
            f"steady <space> recorded {len(steady)} samples, "
            f"expected {_STEADY_SPACE_ROUNDS}"
        )
        rows.append(("steady_space", steady))

        before = len(_read_samples(_perf_jsonl))
        await pilot.press("ctrl+p")
        await pilot.pause()
        single = [
            s
            for s in _read_samples(_perf_jsonl)[before:]
            if s.get("action") == "prompt_cycle_ctrl_p"
        ]
        assert single, "single ctrl+p recorded no prompt_cycle sample"
        rows.append(("single_ctrl_p", single))

        before = len(_read_samples(_perf_jsonl))
        for _ in range(_BURST_KEYS):
            await pilot.press("ctrl+p")
            await pilot.pause(_BURST_CADENCE_S)
        burst = [
            s
            for s in _read_samples(_perf_jsonl)[before:]
            if s.get("action") == "prompt_cycle_ctrl_p"
        ]
        assert len(burst) == _BURST_KEYS, (
            f"ctrl+p burst recorded {len(burst)} samples, expected {_BURST_KEYS}"
        )
        rows.append(("burst_ctrl_p", burst))

    # First visit onto a project whose prompt catalog this session has not
    # requested yet, in a fresh app so no catalog state is warm.
    app2 = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app2.run_test() as pilot:
        await _settle_startup(app2, pilot)
        bar = await _open_space_bar(app2, pilot)
        await pilot.pause()
        text_area = bar.active_text_area()
        text_area.load_text("#git:proj_echo ")
        text_area._vcs_mru_index = None
        text_area.focus()
        await pilot.pause()
        before = len(_read_samples(_perf_jsonl))
        await pilot.press("ctrl+p")
        await pilot.pause()
        first_visit = _read_samples(_perf_jsonl)[before:]
        first_visit = [
            s for s in first_visit if s.get("action") == "prompt_cycle_ctrl_p"
        ]
        assert first_visit, "first-visit ctrl+p recorded no cycle sample"
        rows.append(("first_visit_ctrl_p", first_visit))

    _print_prompt_table("Prompt <space> / <ctrl+p> baseline:", rows)
    print(
        f"  stall-watchdog rows during run: {_stall_row_count(_perf_jsonl)}",
        file=sys.stderr,
    )

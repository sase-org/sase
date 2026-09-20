"""Pytest twin of ``tools/smoke_sase_tool_runs``.

The twin shares the harness's fixtures and cases; it drives the real ``sase`` CLI and
the real Rust-backed store, never a fake application. The full run is ``slow`` (it
includes a 21-second sampling child), so CI runs it through ``just test-slow``.
"""

from __future__ import annotations

import importlib.util
import shutil
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "smoke_sase_tool_runs"
LIVE_CASES = ["dod-8-live-monitor", "dod-8-live-proc"]
# The script imports these siblings by module name; `tools/pyscripts-260801` also
# requires each helper to be referenced from a tracked file outside `tools/`.
HARNESS_MODULES = (
    "_smoke_tool_runs_cases_basic.py",
    "_smoke_tool_runs_cases_evidence.py",
    "_smoke_tool_runs_cases_owners.py",
    "_smoke_tool_runs_helper.py",
    "_smoke_tool_runs_lib.py",
)


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("sase_tool_runs_smoke_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "sase_tool_runs_smoke_tool", SCRIPT, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sase() -> str:
    workspace = ROOT / ".venv" / "bin" / "sase"
    found = str(workspace) if workspace.exists() else shutil.which("sase")
    assert found, "no sase executable: run `just install` first"
    return found


def _failures(report: dict[str, object]) -> list[object]:
    cases = report["cases"]
    assert isinstance(cases, list)
    return [item for item in cases if item["status"] == "fail"]


def test_harness_modules_sit_beside_the_script() -> None:
    missing = [
        name for name in HARNESS_MODULES if not (ROOT / "tools" / name).is_file()
    ]
    assert missing == []


def test_group_ids_are_unique_and_every_case_maps_to_a_dod() -> None:
    tool = _load_tool()
    ids = [case_id for group_ids, _ in tool.GROUPS for case_id in group_ids]
    assert len(ids) == len(set(ids))
    assert "dod-13-overhead" in ids
    # The 21-second sampling case and every DoD owner case are in the default run.
    assert {"dod-6-samples", "dod-9-retention", "dod-9-aggregate-cap"} <= set(ids)


def test_dod_summary_separates_fail_not_run_and_pass() -> None:
    tool = _load_tool()
    cases = [
        {"id": "a", "status": "pass", "dod": ["DoD-1"]},
        {"id": "b", "status": "pass", "dod": ["DoD-2"]},
        {"id": "c", "status": "not-run", "dod": ["DoD-2"]},
        {"id": "d", "status": "fail", "dod": ["DoD-10", "DoD-2"]},
        {"id": "e", "status": "pass", "dod": ["DoD-10"]},
    ]
    summary = {item["id"]: item["status"] for item in tool.dod_summary(cases)}
    assert summary == {"DoD-1": "pass", "DoD-2": "fail", "DoD-10": "fail"}
    only_pending = tool.dod_summary(
        [{"id": "x", "status": "not-run", "dod": ["DoD-8"]}]
    )
    assert only_pending[0]["status"] == "not-run"


def test_harness_environment_is_isolated_from_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "leaky-agent")
    monkeypatch.setenv("SASE_MONITOR_ID", "leaky-monitor")
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "leaky-run")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "leaky::test")
    tool = _load_tool()
    harness = tool.Harness.create(sase=_sase(), live=False, keep=False)
    try:
        env = harness.base_env
        assert not [
            key for key in env if key.startswith("SASE_") and key != "SASE_HOME"
        ]
        assert Path(env["SASE_HOME"]).is_relative_to(harness.tmp)
        assert Path(env["HOME"]).is_relative_to(harness.tmp)
        assert harness.env(HOME=None).get("HOME") is None
        world = harness.world("probe", user_config="tool_runs:\n  log_days: 1\n")
        assert Path(world["SASE_HOME"]).is_relative_to(harness.tmp)
        assert (Path(world["HOME"]) / ".config" / "sase" / "sase.yml").is_file()
    finally:
        harness.cleanup()
    assert not harness.tmp.exists()


@pytest.mark.slow
def test_tool_runs_harness_passes_every_hermetic_case() -> None:
    tool = _load_tool()
    report = tool.run_harness(sase=_sase(), live=False, keep=False)
    statuses = {item["id"]: item["status"] for item in report["cases"]}
    assert _failures(report) == []
    hermetic = [
        case_id
        for group_ids, _ in tool.GROUPS
        for case_id in group_ids
        if case_id not in LIVE_CASES and case_id != "dod-13-overhead"
    ]
    assert [case_id for case_id in hermetic if statuses.get(case_id) != "pass"] == []
    # Live cases are labelled, never silently skipped or reported as passed.
    assert {statuses[case_id] for case_id in LIVE_CASES} == {"not-run"}
    assert statuses["dod-13-overhead"] == "not-run"
    dod = {item["id"]: item["status"] for item in report["dod"]}
    assert all(dod[f"DoD-{n}"] == "pass" for n in (1, 2, 3, 4, 5, 6, 7, 9, 10))
    assert dod["DoD-8"] == "not-run"
    assert report["failed"] == 0
    assert report["loaded_modules"]["core_has_tool_run"] is True


@pytest.mark.slow
def test_tool_runs_harness_live_owner_cases_pass() -> None:
    tool = _load_tool()
    report = tool.run_harness(sase=_sase(), live=True, keep=False, only=LIVE_CASES)
    assert _failures(report) == []
    assert {item["id"]: item["status"] for item in report["cases"]} == dict.fromkeys(
        LIVE_CASES, "pass"
    )
    owners = {item["owner"].split(":")[0] for item in report["runs"]}
    assert owners == {"monitor", "proc"}

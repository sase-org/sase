"""Failure-triage section tests for verify-monitor follow-up prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.tool_run import (
    tool_run_begin,
    tool_run_finish,
    tool_run_observe,
    tool_run_triage_settle,
)
from sase.feature_flags import override_flags
from sase.monitor.followup_prompt import compose_followup_prompt

from ._followup_prompt_fixtures import _COMMON


pytestmark = pytest.mark.skipif(
    not hasattr(__import__("sase_core_rs"), "tool_run_triage_settle"),
    reason="triage bindings are not in this wheel",
)

_TRIAGE = {
    "schema_version": 1,
    "run_id": "run-reserved",
    "run_found": True,
    "triaged": True,
    "verdict": "new_failures",
    "items": [
        {
            "item_id": "new-1",
            "stage_key": "test (scoped)",
            "display": "tests/test_foo.py::test_new",
            "label": {
                "class": "new",
                "evidence": {"rejection_reasons": ["no_witness"]},
                "possible_owners": [],
            },
        },
        {
            "item_id": "unknown-1",
            "stage_key": "lint (mypy)",
            "display": "src/foo.py error",
            "label": {
                "class": "unknown",
                "evidence": {"rejection_reasons": ["no_witness"]},
                "possible_owners": [{"id": "sase-abc"}],
            },
        },
        {
            "item_id": "known-1",
            "stage_key": "lint (symvision)",
            "display": "Unused public functions",
            "label": {
                "class": "known",
                "evidence": {"witness_run_ids": ["run-witness"]},
                "possible_owners": [],
            },
        },
        {
            "item_id": "flaky-1",
            "stage_key": "test (scoped)",
            "display": "tests/test_flaky.py::test_it",
            "label": {
                "class": "flaky",
                "evidence": {"baseline_line": "tests/test_flaky.py::test_it"},
                "possible_owners": [],
            },
        },
    ],
}


def _prompt(**kwargs: object) -> str:
    payload = {
        "starter_name": "acme--0",
        "monitor_state": "failed",
        "exit_code": 1,
        "elapsed_seconds": 42.0,
        "timeout_seconds": 2700.0,
        **_COMMON,
        **kwargs,
    }
    return compose_followup_prompt(**payload)  # type: ignore[arg-type]


def test_flag_off_followup_omits_triage_section() -> None:
    with override_flags(tool_failure_triage=False):
        prompt = _prompt(tool_run_id="run-reserved", triage=_TRIAGE)
    assert "## Failure triage" not in prompt
    assert "verdict: new_failures" not in prompt
    assert "## Selected diagnostics" not in prompt


def test_flag_on_followup_inserts_triage_before_diagnostics() -> None:
    diagnostics = "pytest failed\n"
    with override_flags(tool_failure_triage=True):
        prompt = _prompt(
            tool_run_id="run-reserved",
            triage=_TRIAGE,
            diagnostic_manifest={
                "schema_version": 1,
                "producer": "test",
                "manifest_ref": "file:explicit:diagnostics",
                "complete": False,
                "stages": [
                    {
                        "stage_id": "pytest",
                        "name": "pytest",
                        "status": "failed",
                        "exit_code": 1,
                        "diagnostic_refs": ["file:explicit:pytest-log"],
                    }
                ],
            },
            selected_diagnostics_text=diagnostics,
        )
    triage_at = prompt.index("## Failure triage")
    diagnostics_at = prompt.index("## Selected diagnostics")
    assert triage_at < diagnostics_at
    assert "verdict: new_failures" in prompt
    assert "NEW test (scoped): tests/test_foo.py::test_new" in prompt
    assert "UNKNOWN lint (mypy): src/foo.py error" in prompt
    assert "possible owner sase-abc" in prompt
    assert "KNOWN 1; FLAKY 1" in prompt
    assert "sase tool show run-reserved -j" in prompt
    assert (
        "The starter"
        not in prompt.split("## Failure triage", 1)[1].split(
            "## Selected diagnostics", 1
        )[0]
    )


def _seed_owned_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    owner_kind: str | None,
    owner_id: str | None,
) -> str:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    request: dict[str, object] = {
        "schema_version": 1,
        "tool_name": "check",
        "definition": {
            "schema_version": 1,
            "name": "check",
            "argv": ["just", "check"],
            "description": "check",
            "stages": "run_silent",
            "inputs": ["Justfile"],
            "env": [],
            "args": "deny",
            "fingerprint": {"repos": [], "toolchain": {}},
        },
        "display_argv": ["just", "check"],
        "project": "sase",
        "workspace": "ws",
        "now_ts": 1_700_000_000,
        "commit_running": True,
        "agent": "starter-1",
    }
    if owner_kind and owner_id:
        request["owner_kind"] = owner_kind
        request["owner_id"] = owner_id
    run_id = tool_run_begin(request)["run"]["run_id"]
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "sase",
                "repos": [{"identity": "sase", "head": "head", "dirty_paths": []}],
                "completeness": {"complete": True},
            },
        }
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 1,
            "duration_ms": 1,
            "now_ts": 1_700_000_001,
        }
    )
    tool_run_triage_settle(
        {
            "run_id": run_id,
            "stages": [
                {
                    "stage_key": "lint (mypy)",
                    "stage_id": "stage-1",
                    "output": "src/foo.py:10:5: error: Bad thing  [attr-defined]\n",
                    "truncated": False,
                    "output_path": "logs/stage.log",
                }
            ],
            "project_root": str(tmp_path),
            "workspace_roots": [],
            "ancestry": ["head"],
            "flake_baseline": [],
            "selection_records": [],
            "owner_candidates": [],
            "knobs": {
                "min_witnesses": 1,
                "touched_requires_clean_witness": False,
            },
            "continuation_mode": "never",
            "recipe_finished_ts": 1_700_000_002,
            "now_ts": 1_700_000_002,
        }
    )
    return run_id


def test_reserved_run_followup_loads_stored_triage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = _seed_owned_run(
        monkeypatch, tmp_path, owner_kind="monitor", owner_id="mon-reserved"
    )
    with override_flags(tool_failure_triage=True):
        prompt = _prompt(tool_run_id=run_id, monitor_id="other-monitor")
    assert "## Failure triage" in prompt
    assert f"sase tool show {run_id} -j" in prompt
    assert "UNKNOWN lint (mypy):" in prompt
    assert "The starter" not in prompt


def test_wrapped_just_check_followup_resolves_monitor_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = _seed_owned_run(
        monkeypatch, tmp_path, owner_kind="monitor", owner_id="m4kqm4kqm4kq"
    )
    with override_flags(tool_failure_triage=True):
        prompt = _prompt(tool_run_id=None)
    assert "## Failure triage" in prompt
    assert f"sase tool show {run_id} -j" in prompt
    assert "UNKNOWN lint (mypy):" in prompt

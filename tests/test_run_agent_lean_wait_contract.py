"""Contract tests for the lean waiter's spec, import firewall, and shared leaves."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from sase.axe import run_agent_wait_deps, run_agent_wait_ready
from sase.axe.run_agent_lean_wait import (
    DEFAULT_HEALTHY_PROBE_INTERVAL_SECONDS,
    DEFAULT_HEARTBEAT_FRESH_SECONDS,
    DEFAULT_PROBE_INTERVAL_SECONDS,
    DEFAULT_PROBE_TIMEOUT_SECONDS,
    validate_lean_wait_spec,
)
from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
from sase.env_contracts import SASE_RUNNER_CODE_REFRESHED_ENV


def _raw_spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "version": 1,
        "artifacts_dir": "/tmp/artifacts/20261121",
        "project_name": "proj",
        "runner_argv": ["/usr/bin/python", "run_agent_runner.py", "--x"],
        "mode": "dependency",
        "deadline_epoch": None,
        "heartbeat_path": "/tmp/hb",
        "bead_sync_hint": True,
        "bead_sync_role": "beads",
        "blocked_since": 100.0,
        "handed_off_at": 130.0,
    }
    spec.update(overrides)
    return spec


def test_valid_spec_parses_with_contract_defaults() -> None:
    spec = validate_lean_wait_spec(_raw_spec())

    assert spec.artifacts_dir == "/tmp/artifacts/20261121"
    assert spec.project_name == "proj"
    assert spec.runner_argv == ("/usr/bin/python", "run_agent_runner.py", "--x")
    assert spec.mode == "dependency"
    assert spec.deadline_epoch is None
    assert spec.heartbeat_path == "/tmp/hb"
    assert spec.bead_sync_hint is True
    assert spec.bead_sync_role == "beads"
    assert (spec.blocked_since, spec.handed_off_at) == (100.0, 130.0)
    assert (
        spec.probe_interval_s,
        spec.healthy_probe_interval_s,
        spec.heartbeat_fresh_s,
        spec.probe_timeout_s,
    ) == (60.0, 1800.0, 300.0, 300.0)
    assert DEFAULT_PROBE_INTERVAL_SECONDS == 60.0
    assert DEFAULT_HEALTHY_PROBE_INTERVAL_SECONDS == 1800.0
    assert DEFAULT_HEARTBEAT_FRESH_SECONDS == 300.0
    assert DEFAULT_PROBE_TIMEOUT_SECONDS == 300.0


def test_optional_tuning_fields_override_the_defaults() -> None:
    spec = validate_lean_wait_spec(
        _raw_spec(
            probe_interval_s=1,
            healthy_probe_interval_s=2.5,
            heartbeat_fresh_s=3,
            probe_timeout_s=4,
        )
    )

    assert (
        spec.probe_interval_s,
        spec.healthy_probe_interval_s,
        spec.heartbeat_fresh_s,
        spec.probe_timeout_s,
    ) == (1.0, 2.5, 3.0, 4.0)


@pytest.mark.parametrize("mode", ["duration", "until"])
def test_time_modes_require_a_deadline_and_dependency_mode_forbids_one(
    mode: str,
) -> None:
    spec = validate_lean_wait_spec(
        _raw_spec(mode=mode, deadline_epoch=1_800_000_000.5, project_name=None)
    )
    assert spec.deadline_epoch == 1_800_000_000.5
    assert spec.project_name is None

    with pytest.raises(ValueError, match="deadline_epoch is required"):
        validate_lean_wait_spec(_raw_spec(mode=mode))
    with pytest.raises(ValueError, match="null in dependency mode"):
        validate_lean_wait_spec(_raw_spec(deadline_epoch=5.0))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"version": 2}, "version"),
        ({"version": True}, "version"),
        ({"version": None}, "version"),
        ({"artifacts_dir": "relative/dir"}, "artifacts_dir"),
        ({"artifacts_dir": 7}, "artifacts_dir"),
        ({"runner_argv": []}, "runner_argv"),
        ({"runner_argv": ["python", 3]}, "runner_argv"),
        ({"runner_argv": [""]}, "runner_argv"),
        ({"runner_argv": "python run.py"}, "runner_argv"),
        ({"mode": "forever"}, "mode"),
        ({"project_name": ""}, "project_name"),
        ({"project_name": 3}, "project_name"),
        ({"heartbeat_path": 3}, "heartbeat_path"),
        ({"bead_sync_hint": "yes"}, "bead_sync_hint"),
        ({"bead_sync_role": None}, "bead_sync_role"),
        ({"blocked_since": None}, "blocked_since"),
        ({"handed_off_at": "now"}, "handed_off_at"),
        ({"handed_off_at": True}, "handed_off_at"),
        ({"handed_off_at": float("inf")}, "handed_off_at"),
        ({"probe_interval_s": 0}, "probe_interval_s"),
        ({"healthy_probe_interval_s": -1}, "healthy_probe_interval_s"),
        ({"heartbeat_fresh_s": "5"}, "heartbeat_fresh_s"),
        ({"probe_timeout_s": float("nan")}, "probe_timeout_s"),
    ],
)
def test_invalid_specs_are_rejected_with_the_field_name(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_lean_wait_spec(_raw_spec(**overrides))


@pytest.mark.parametrize("raw", [None, [], "spec", 3])
def test_a_non_object_spec_is_rejected(raw: object) -> None:
    with pytest.raises(ValueError, match="JSON object"):
        validate_lean_wait_spec(raw)


def test_a_round_tripped_json_spec_validates() -> None:
    raw = json.loads(json.dumps(_raw_spec(probe_interval_s=0.5)))

    assert validate_lean_wait_spec(raw).probe_interval_s == 0.5


_IMPORT_SNAPSHOT = (
    "import json, sys\n"
    "import {module}\n"
    "print(json.dumps({{\n"
    "    'loaded': sorted(sys.modules),\n"
    "    'stdlib': sorted(sys.stdlib_module_names),\n"
    "}}))\n"
)


def _loaded_modules(module: str) -> tuple[set[str], set[str]]:
    completed = subprocess.run(
        [sys.executable, "-c", _IMPORT_SNAPSHOT.format(module=module)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    payload = json.loads(completed.stdout)
    return set(payload["loaded"]), set(payload["stdlib"])


# What ``import sase.axe.run_agent_lean_wait`` may pull in beyond the standard
# library: the waiter and its two allowlisted leaves, plus the package inits and
# the lazy-export helper ``sase.axe`` loads. Anything else (config, the wait
# resolver, the Rust binding, telemetry) breaks the ~15 MB budget.
_WAITER_SASE_ALLOWLIST = {
    "sase",
    "sase._lazy_exports",
    "sase.axe",
    "sase.axe.run_agent_lean_wait",
    "sase.axe.run_agent_wait_ready",
    "sase.env_contracts",
}


def _non_stdlib_modules(loaded: set[str], stdlib: set[str]) -> set[str]:
    """Loaded modules outside the stdlib, ignoring editable-install finders."""
    return {
        name
        for name in loaded
        if name.split(".")[0] not in stdlib
        and name != "__main__"
        and not name.startswith(("__editable__", "_distutils_hack", "_virtualenv"))
    }


def test_lean_waiter_import_firewall() -> None:
    loaded, stdlib = _loaded_modules("sase.axe.run_agent_lean_wait")

    assert _non_stdlib_modules(loaded, stdlib) == _WAITER_SASE_ALLOWLIST
    for forbidden in (
        "sase.config",
        "sase.core",
        "sase.core.wait_dependency_resolution",
        "sase_core_rs",
        "sase.axe.run_agent_wait_deps",
        "sase.axe.run_agent_wait_markers",
    ):
        assert forbidden not in loaded


def test_ready_marker_leaf_is_stdlib_only() -> None:
    loaded, stdlib = _loaded_modules("sase.axe.run_agent_wait_ready")

    assert _non_stdlib_modules(loaded, stdlib) == {
        "sase",
        "sase._lazy_exports",
        "sase.axe",
        "sase.axe.run_agent_wait_ready",
    }


def test_wait_deps_reexports_the_ready_marker_leaf() -> None:
    assert (
        run_agent_wait_deps.read_ready_result is run_agent_wait_ready.read_ready_result
    )
    assert run_agent_wait_deps.ReadyResult is run_agent_wait_ready.ReadyResult


def test_runner_wait_module_still_exposes_the_monkeypatch_target() -> None:
    import sase.axe.run_agent_wait as run_agent_wait

    assert run_agent_wait.read_ready_result is run_agent_wait_ready.read_ready_result


def test_runner_refresh_guard_env_name_is_the_shared_contract() -> None:
    assert RUNNER_CODE_REFRESHED_ENV == SASE_RUNNER_CODE_REFRESHED_ENV
    assert SASE_RUNNER_CODE_REFRESHED_ENV == "SASE_RUNNER_CODE_REFRESHED"

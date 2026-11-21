"""``agent_scope.slice`` places agent, monitor, and proc scopes in a slice."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

import sase.scope_slice as slice_module
from sase.config._settings_system import get_agent_scope_slice
from sase.detach_scope import DETACH_SCOPE_DISABLE_ENV, detach_scope
from sase.scope_slice import (
    WORKLOAD_SLICE_UNIT_PREFIXES,
    is_valid_slice_name,
    slice_cgroup_components,
)

_SYSTEMD_RUN = "/usr/bin/systemd-run"
_BASE_ARGV = [
    _SYSTEMD_RUN,
    "--user",
    "--scope",
    "--quiet",
    "--collect",
    "--unit=sase-agent-123-456",
    "--description=SASE agent runner",
    "--",
    "/usr/bin/sase",
    "agent",
]


@pytest.fixture
def linux_systemd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make detach_scope take the systemd-run path from a sase.service cgroup."""
    proc_root = tmp_path / "proc"
    (proc_root / "123").mkdir(parents=True)
    (proc_root / "123" / "cgroup").write_text(
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/sase.service\n",
        encoding="utf-8",
    )
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "linux")
    monkeypatch.setattr("sase.detach_scope.os.getpid", lambda: 123)
    monkeypatch.setattr("sase.detach_scope.time.time_ns", lambda: 456)
    monkeypatch.setattr(
        "sase.detach_scope.shutil.which",
        lambda name: _SYSTEMD_RUN if name == "systemd-run" else None,
    )
    monkeypatch.setattr("sase.detach_scope._systemd_run_version", lambda _p: None)
    monkeypatch.setattr("sase.scope_slice._slice_probe_results", {})
    return proc_root


def _configure(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]) -> None:
    monkeypatch.setattr("sase.config._settings_system._merged_config", lambda: config)


def _probe_calls(
    monkeypatch: pytest.MonkeyPatch, *, accepted: bool = True
) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def fake_probe(systemd_run: str, slice_name: str) -> tuple[bool, str]:
        calls.append((systemd_run, slice_name))
        return accepted, "" if accepted else "Unit x.slice is masked."

    monkeypatch.setattr("sase.scope_slice._probe_slice", fake_probe)
    return calls


def _launch(proc_root: Path, unit_prefix: str = "sase-agent") -> Any:
    return detach_scope(
        ["/usr/bin/sase", "agent"],
        description="SASE agent runner",
        unit_prefix=unit_prefix,
        proc_root=proc_root,
    )


def test_unset_slice_keeps_argv_byte_for_byte(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, {})
    calls = _probe_calls(monkeypatch)

    launch = _launch(linux_systemd)

    assert launch.argv == _BASE_ARGV
    assert launch.slice_name is None
    assert calls == []


def test_explicit_null_slice_keeps_argv(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, {"agent_scope": {"slice": None}})
    calls = _probe_calls(monkeypatch)

    assert _launch(linux_systemd).argv == _BASE_ARGV
    assert calls == []


@pytest.mark.parametrize("unit_prefix", sorted(WORKLOAD_SLICE_UNIT_PREFIXES))
def test_configured_slice_applies_to_workload_scopes(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch, unit_prefix: str
) -> None:
    _configure(monkeypatch, {"agent_scope": {"slice": "sase-agents.slice"}})
    calls = _probe_calls(monkeypatch)

    launch = _launch(linux_systemd, unit_prefix)

    separator = launch.argv.index("--")
    assert "--slice=sase-agents.slice" in launch.argv[:separator]
    assert launch.argv[separator:] == ["--", "/usr/bin/sase", "agent"]
    assert launch.slice_name == "sase-agents.slice"
    assert calls == [(_SYSTEMD_RUN, "sase-agents.slice")]


def test_workload_prefixes_are_exactly_agent_monitor_proc() -> None:
    assert WORKLOAD_SLICE_UNIT_PREFIXES == {"sase-agent", "sase-monitor", "sase-proc"}


@pytest.mark.parametrize(
    "unit_prefix",
    ["sase-service", "sase-federation", "sase-axe", "sase-checks", "sase-tmux"],
)
def test_configured_slice_never_applies_to_other_scopes(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch, unit_prefix: str
) -> None:
    _configure(monkeypatch, {"agent_scope": {"slice": "sase-agents.slice"}})
    calls = _probe_calls(monkeypatch)

    launch = _launch(linux_systemd, unit_prefix)

    assert not any(arg.startswith("--slice") for arg in launch.argv)
    assert launch.slice_name is None
    assert calls == []


def test_rejected_slice_falls_back_with_warning(
    linux_systemd: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure(monkeypatch, {"agent_scope": {"slice": "sase-agents.slice"}})
    calls = _probe_calls(monkeypatch, accepted=False)

    with caplog.at_level(logging.WARNING, logger="sase.scope_slice"):
        first = _launch(linux_systemd)
        second = _launch(linux_systemd, "sase-monitor")

    assert first.argv == _BASE_ARGV
    assert first.escaped is True
    assert first.slice_name is None
    assert not any(arg.startswith("--slice") for arg in second.argv)
    # The rejection is cached: one probe and one warning for both launches.
    assert len(calls) == 1
    warnings = [r for r in caplog.records if "rejected agent_scope.slice" in r.message]
    assert len(warnings) == 1
    assert "is masked" in warnings[0].getMessage()


def test_rejected_slice_is_reprobed_after_retry_window(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, {"agent_scope": {"slice": "sase-agents.slice"}})
    calls = _probe_calls(monkeypatch, accepted=False)
    now = [1000.0]
    monkeypatch.setattr("sase.scope_slice.time.monotonic", lambda: now[0])

    _launch(linux_systemd)
    now[0] += slice_module._SLICE_PROBE_RETRY_SECONDS - 1  # noqa: SLF001
    _launch(linux_systemd)
    assert len(calls) == 1
    now[0] += 2
    _launch(linux_systemd)
    assert len(calls) == 2


def test_accepted_slice_is_probed_once(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, {"agent_scope": {"slice": "sase-agents.slice"}})
    calls = _probe_calls(monkeypatch)

    for prefix in ("sase-agent", "sase-monitor", "sase-proc", "sase-agent"):
        assert "--slice=sase-agents.slice" in _launch(linux_systemd, prefix).argv
    assert len(calls) == 1


def test_config_read_failure_launches_without_slice(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> dict[str, Any]:
        raise RuntimeError("config exploded")

    monkeypatch.setattr("sase.config._settings_system._merged_config", broken)
    calls = _probe_calls(monkeypatch)

    assert _launch(linux_systemd).argv == _BASE_ARGV
    assert calls == []


def test_disabled_and_macos_paths_ignore_slice(
    linux_systemd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, {"agent_scope": {"slice": "sase-agents.slice"}})
    calls = _probe_calls(monkeypatch)

    monkeypatch.setenv(DETACH_SCOPE_DISABLE_ENV, "1")
    assert _launch(linux_systemd).argv == ["/usr/bin/sase", "agent"]
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV)
    monkeypatch.setattr("sase.detach_scope.sys.platform", "darwin")
    assert _launch(linux_systemd).argv == ["/usr/bin/sase", "agent"]
    assert calls == []


def test_probe_runs_throwaway_scope_in_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 1, "", "Unit a.slice is masked.\n")

    monkeypatch.setattr("sase.scope_slice.subprocess.run", fake_run)
    monkeypatch.setattr("sase.scope_slice.os.getpid", lambda: 7)
    monkeypatch.setattr("sase.scope_slice.time.time_ns", lambda: 8)

    accepted, detail = slice_module._probe_slice(_SYSTEMD_RUN, "a.slice")  # noqa: SLF001

    assert (accepted, detail) == (False, "Unit a.slice is masked.")
    assert captured["argv"] == [
        _SYSTEMD_RUN,
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "--unit=sase-slice-probe-7-8",
        "--description=SASE slice probe",
        "--slice=a.slice",
        "--",
        "true",
    ]
    assert captured["kwargs"]["timeout"] > 0


def test_probe_treats_timeout_as_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **_kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr("sase.scope_slice.subprocess.run", fake_run)

    accepted, _detail = slice_module._probe_slice(_SYSTEMD_RUN, "a.slice")  # noqa: SLF001

    assert accepted is False


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("sase-agents.slice", True),
        ("sase.slice", True),
        ("a-b-c.slice", True),
        ("sase_agents.slice", True),
        ("sase-agents", False),
        ("sase-agents.service", False),
        ("a--b.slice", False),
        ("-a.slice", False),
        ("a-.slice", False),
        ("-.slice", False),
        ("sase agents.slice", False),
        ("sase/agents.slice", False),
        ("", False),
        ("a" * 250 + ".slice", False),
    ],
)
def test_is_valid_slice_name(name: str, valid: bool) -> None:
    assert is_valid_slice_name(name) is valid


def test_slice_cgroup_components_follow_dash_nesting() -> None:
    assert slice_cgroup_components("sase.slice") == ("sase.slice",)
    assert slice_cgroup_components("sase-agents.slice") == (
        "sase.slice",
        "sase-agents.slice",
    )
    assert slice_cgroup_components("a-b-c.slice") == (
        "a.slice",
        "a-b.slice",
        "a-b-c.slice",
    )


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, None),
        ({"agent_scope": None}, None),
        ({"agent_scope": {}}, None),
        ({"agent_scope": {"slice": None}}, None),
        ({"agent_scope": {"slice": "sase-agents.slice"}}, "sase-agents.slice"),
        ({"agent_scope": {"slice": "  sase-agents.slice "}}, "sase-agents.slice"),
        ({"agent_scope": {"slice": "sase-agents"}}, None),
        ({"agent_scope": {"slice": "a--b.slice"}}, None),
        ({"agent_scope": {"slice": 7}}, None),
    ],
)
def test_get_agent_scope_slice(
    monkeypatch: pytest.MonkeyPatch, config: dict[str, Any], expected: str | None
) -> None:
    _configure(monkeypatch, config)
    assert get_agent_scope_slice() == expected

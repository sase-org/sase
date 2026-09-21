"""Antigravity `/usage` collector: version floor, wire name, decode, cleanup."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.llm_provider.agy import AgyProvider
from sase.llm_provider.usage.probe import default_probe_context, run_usage_probe
from sase.llm_provider.usage.refresh import eligible_usage_providers
from tests.llm_provider._provider_config_helpers import mock_provider_config

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "usage_probe" / "agy_usage_cli.py"
)

_GEMINI_IDS = [
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low",
    "gemini-3.7-flash-high",
    "gemini-3.7-flash-medium",
    "gemini-3.7-flash-low",
    "gemini-3.6-flash-high",
    "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low",
    "gemini-3.5-flash-high",
    "gemini-3.5-flash-medium",
    "gemini-3.5-flash-low",
    "gemini-3.1-pro-high",
    "gemini-3.1-pro-low",
]
_3P_IDS = [
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
]


def _make_fake_agy(tmp_path: Path) -> Path:
    path = tmp_path / "agy"
    shutil.copy(_FIXTURE, path)
    path.chmod(0o755)
    return path


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _run_agy_probe(
    fake_agy: Path,
    tmp_path: Path,
    *,
    mode: str = "success",
    version: str = "1.2.7",
    version_exit: str = "0",
    payload: dict[str, Any] | None = None,
    deadline_seconds: float = 5.0,
    executable: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    argv_path = tmp_path / "argv.jsonl"
    pidfile = tmp_path / "agy.pid"
    env = {
        "SASE_FAKE_AGY_MODE": mode,
        "SASE_FAKE_AGY_VERSION": version,
        "SASE_FAKE_AGY_VERSION_EXIT": version_exit,
        "SASE_FAKE_AGY_ARGV": str(argv_path),
        "SASE_FAKE_AGY_PIDFILE": str(pidfile),
    }
    if payload is not None:
        env["SASE_FAKE_AGY_PAYLOAD"] = json.dumps(payload)
    now = time.time()
    context = default_probe_context(
        "agy",
        now=now,
        deadline_seconds=deadline_seconds,
        executable=str(executable or fake_agy),
    )
    started = time.time()
    probe_result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec={"kind": "entry_point", "name": "agy"},
        now=now,
        env=env,
    )
    elapsed = time.time() - started
    result = probe_result.observation
    assert result is not None
    return result, _read_json_lines(argv_path), elapsed


def _read_json_lines(path: Path) -> list[Any]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = subprocess.check_output(
            ["ps", "-o", "stat=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return False
    return not state.startswith("Z")


def _process_group_gone(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _usage_argv(entries: list[dict[str, Any]]) -> list[str]:
    for entry in entries:
        argv = entry["argv"]
        if len(argv) >= 2 and argv[0] == "-p" and argv[1] == "/usage":
            return argv
    raise AssertionError(f"/usage argv not recorded: {entries!r}")


def test_agy_provider_declares_usage_probe_capability() -> None:
    assert AgyProvider().llm_usage_capabilities() == {
        "probe": True,
        "passive_events": False,
    }


def test_agy_usage_probe_collects_four_windows(tmp_path: Path) -> None:
    fake = _make_fake_agy(tmp_path)
    result, entries, _ = _run_agy_probe(fake, tmp_path)
    assert result["outcome"] == "ok"
    assert result["account_mode"] == "subscription"
    assert result["plan"] is None
    assert result["completeness"] == "complete"
    by_key = {window["key"]: window for window in result["windows"]}
    assert sorted(by_key) == ["3p-5h", "3p-weekly", "gemini-5h", "gemini-weekly"]

    weekly = by_key["gemini-weekly"]
    assert weekly["label"] == "Gemini Models Weekly Limit Remaining"
    assert weekly["used_percent"] == pytest.approx(3.8758575916290307)
    assert weekly["resets_at"] == pytest.approx(_epoch("2026-09-27T20:14:34Z"))
    assert weekly["period_start"] == pytest.approx(
        _epoch("2026-09-27T20:14:34Z") - 604800.0
    )
    assert weekly["duration_seconds"] == pytest.approx(604800.0)
    assert weekly["applicability"] == {
        "kind": "model_family",
        "family": "gemini",
        "model_ids": _GEMINI_IDS,
    }
    assert weekly["vendor_state"] == "allowed"
    assert weekly["source"] == "probe"

    five_hour = by_key["gemini-5h"]
    assert five_hour["used_percent"] == pytest.approx(13.350301980972285)
    assert five_hour["resets_at"] == pytest.approx(_epoch("2026-09-21T23:31:12Z"))
    assert five_hour["duration_seconds"] == pytest.approx(18000.0)
    assert five_hour["applicability"]["family"] == "gemini"

    for key in ("3p-weekly", "3p-5h"):
        window = by_key[key]
        assert window["used_percent"] == pytest.approx(0.0)
        assert window["applicability"] == {
            "kind": "model_family",
            "family": "3p",
            "model_ids": _3P_IDS,
        }

    argv_lists = [entry["argv"] for entry in entries]
    assert argv_lists[0] == ["--version"]
    usage_argv = _usage_argv(entries)
    assert usage_argv[2:8] == [
        "--output-format",
        "json",
        "--mode",
        "plan",
        "--sandbox",
        "--print-timeout",
    ]
    assert usage_argv[8] == "15s"
    log_index = usage_argv.index("--log-file")
    log_file = usage_argv[log_index + 1]
    assert log_file.endswith("/agy-usage.log")
    usage_entry = next(entry for entry in entries if entry["argv"] == usage_argv)
    assert usage_entry["no_auto_update"] == "1"
    assert usage_entry["cwd"] == str(Path(log_file).parent)


def test_agy_usage_probe_old_version_never_spawns_usage(tmp_path: Path) -> None:
    fake = _make_fake_agy(tmp_path)
    result, entries, _ = _run_agy_probe(fake, tmp_path, version="1.0.10")
    assert result["outcome"] == "unsupported"
    assert result["reason_code"] == "unsupported_cli_version"
    assert [entry["argv"] for entry in entries] == [["--version"]]


def test_agy_usage_probe_unparseable_version_never_spawns_usage(
    tmp_path: Path,
) -> None:
    fake = _make_fake_agy(tmp_path)
    result, entries, _ = _run_agy_probe(fake, tmp_path, version="banana")
    assert result["outcome"] == "unsupported"
    assert result["reason_code"] == "unsupported_cli_version"
    assert [entry["argv"] for entry in entries] == [["--version"]]


def test_agy_usage_probe_failed_version_probe_is_unsupported(
    tmp_path: Path,
) -> None:
    fake = _make_fake_agy(tmp_path)
    result, _, _ = _run_agy_probe(fake, tmp_path, version_exit="1")
    assert result["outcome"] == "unsupported"
    assert result["reason_code"] == "unsupported_cli_version"


def test_agy_usage_probe_auth_prompt_is_logged_out_fast(tmp_path: Path) -> None:
    fake = _make_fake_agy(tmp_path)
    result, _, elapsed = _run_agy_probe(fake, tmp_path, mode="auth_prompt")
    assert result["outcome"] == "unauthenticated"
    assert result["reason_code"] == "logged_out"
    assert elapsed < 4.0
    pid = int((tmp_path / "agy.pid").read_text(encoding="utf-8").strip())
    assert not _pid_alive(pid)
    assert _process_group_gone(pid)


def test_agy_usage_probe_hang_is_timeout_and_reaps_child(
    tmp_path: Path,
) -> None:
    fake = _make_fake_agy(tmp_path)
    result, _, _ = _run_agy_probe(fake, tmp_path, mode="hang", deadline_seconds=3.0)
    assert result["outcome"] == "error"
    assert result["reason_code"] == "timeout"
    pid = int((tmp_path / "agy.pid").read_text(encoding="utf-8").strip())
    assert not _pid_alive(pid)
    assert _process_group_gone(pid)


def test_agy_usage_probe_malformed_stdout_is_parse_error(
    tmp_path: Path,
) -> None:
    fake = _make_fake_agy(tmp_path)
    result, _, _ = _run_agy_probe(fake, tmp_path, mode="malformed")
    assert result["outcome"] == "error"
    assert result["reason_code"] == "parse_error"


def test_agy_usage_probe_omitted_zero_row_is_exhausted(
    tmp_path: Path,
) -> None:
    fake = _make_fake_agy(tmp_path)
    result, _, _ = _run_agy_probe(fake, tmp_path, mode="omitted_zero")
    assert result["outcome"] == "ok"
    by_key = {window["key"]: window for window in result["windows"]}
    assert by_key["gemini-5h"]["used_percent"] == pytest.approx(100.0)


def test_agy_usage_probe_turn_ran_is_vendor_drift(tmp_path: Path) -> None:
    fake = _make_fake_agy(tmp_path)
    result, _, _ = _run_agy_probe(fake, tmp_path, mode="turn_ran")
    assert result["outcome"] == "error"
    assert result["reason_code"] == "vendor_drift"


def test_agy_usage_probe_missing_executable_is_not_installed(
    tmp_path: Path,
) -> None:
    fake = _make_fake_agy(tmp_path)
    result, _, _ = _run_agy_probe(fake, tmp_path, executable="/nonexistent/agy-xyz")
    assert result["outcome"] == "error"
    assert result["reason_code"] == "not_installed"


def test_agy_probe_log_file_is_owner_only(tmp_path: Path) -> None:
    from sase.llm_provider.usage.agy import _precreate_private_log

    _precreate_private_log(str(tmp_path))
    mode = stat.S_IMODE((tmp_path / "agy-usage.log").stat().st_mode)
    assert mode == 0o600


def _enable_agy_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {"usage_metrics": {"enabled": True, "providers": {"agy": {"enabled": True}}}},
    )


def _pin_agy_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["agy"],
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_picker_hidden_provider_names",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh._referenced_provider_ids",
        lambda: set(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "agy": {
                    "usage_capabilities": {"probe": True},
                    "autodetect_cli_name": "agy",
                }
            }
        },
    )


def test_agy_is_eligible_when_cli_resolvable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _pin_agy_registry(monkeypatch)
    _enable_agy_collection(monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    agy = bin_dir / "agy"
    agy.write_text("#!/bin/sh\n")
    agy.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("SASE_AGY_PATH", raising=False)
    assert eligible_usage_providers() == ("agy",)


def test_agy_is_ineligible_without_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _pin_agy_registry(monkeypatch)
    _enable_agy_collection(monkeypatch)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("SASE_AGY_PATH", raising=False)
    assert eligible_usage_providers() == ()

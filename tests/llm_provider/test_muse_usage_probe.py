"""Muse Code MSP echo-mint usage collector: sequence, guard, absence, mapping."""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from sase.llm_provider.muse import MuseProvider
from sase.llm_provider.usage.probe import default_probe_context, run_usage_probe

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "usage_probe" / "muse_msp_cli.py"
)
_LIVE_USAGE = {
    "observedAtMs": 1789921255705,
    "tier": "27681631238169137",
    "weekly": {"resetsAtMs": 1789948800000, "usedPercent": 0},
    "window": {
        "resetsAtMs": 1789935797000,
        "usedPercent": 0,
        "windowDurationMins": 300,
    },
}
# What the probe must send, in order, before it starts polling ``usage/read``.
_SEQUENCE_PREFIX = ["initialize", "initialized", "session/start", "turn/start"]


def _make_fake_muse(tmp_path: Path) -> Path:
    path = tmp_path / "muse"
    shutil.copy(_FIXTURE, path)
    path.chmod(0o755)
    return path


def _fake_env(
    tmp_path: Path,
    *,
    mode: str = "native",
    usage: object | None = None,
    mint_after_polls: int = 2,
    fingerprint: str | None = None,
) -> dict[str, str]:
    env = {
        "SASE_FAKE_MUSE_MODE": mode,
        "SASE_FAKE_MUSE_MESSAGES": str(tmp_path / "messages.jsonl"),
        "SASE_FAKE_MUSE_ARGV": str(tmp_path / "argv.jsonl"),
        "SASE_FAKE_MUSE_MINT_AFTER_POLLS": str(mint_after_polls),
    }
    if usage is not None:
        env["SASE_FAKE_MUSE_USAGE"] = json.dumps(usage)
    if fingerprint is not None:
        env["SASE_FAKE_MUSE_FINGERPRINT"] = fingerprint
    return env


def _read_json_lines(path: Path) -> list[Any]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _run_muse_probe(
    fake_muse: Path | str,
    tmp_path: Path,
    *,
    mode: str = "native",
    usage: object | None = None,
    mint_after_polls: int = 2,
    deadline_seconds: float = 8.0,
    working_directory: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    env = _fake_env(tmp_path, mode=mode, usage=usage, mint_after_polls=mint_after_polls)
    now = time.time()
    context = default_probe_context(
        "muse",
        now=now,
        deadline_seconds=deadline_seconds,
        executable=str(fake_muse),
        working_directory=working_directory,
    )
    probe_result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec={"kind": "entry_point", "name": "muse"},
        now=now,
        env=env,
    )
    observation = probe_result.observation
    assert observation is not None
    return (
        observation,
        _read_json_lines(tmp_path / "messages.jsonl"),
        _read_json_lines(tmp_path / "argv.jsonl"),
    )


def _methods(messages: list[dict[str, Any]]) -> list[str]:
    return [message["method"] for message in messages]


def test_muse_provider_declares_usage_probe_capability() -> None:
    assert MuseProvider().llm_usage_capabilities() == {
        "probe": True,
        "passive_events": False,
    }


def test_muse_usage_probe_mints_with_the_minimal_echo_sequence(
    tmp_path: Path,
) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, argv = _run_muse_probe(fake, tmp_path)

    methods = _methods(messages)
    assert methods[: len(_SEQUENCE_PREFIX)] == _SEQUENCE_PREFIX
    polls = methods[len(_SEQUENCE_PREFIX) :]
    assert polls == ["usage/read"] * len(polls)
    assert len(polls) == 3  # two cold reads, then the mint lands

    initialize, initialized, start, turn = messages[:4]
    assert re.fullmatch(r"[a-z0-9_]+", initialize["params"]["clientInfo"]["name"])
    assert "id" not in initialized
    assert "params" not in initialized
    assert start["params"]["providerId"] == "echo"
    assert turn["params"]["sessionId"] == "01a0bfd8-88b9-7661-a94b-07b71bcc5c77"
    assert turn["params"]["input"] == [{"type": "text", "text": "hi"}]
    assert turn["params"]["reasoningEffort"] == "none"
    command_ids = [start["params"]["commandId"], turn["params"]["commandId"]]
    assert len(set(command_ids)) == 2
    assert all(uuid.UUID(command_id).version == 7 for command_id in command_ids)

    assert argv[0]["argv"] == ["serve", "--no-session-log", "--disable-shell"]
    assert argv[0]["no_auto_update"] == "1"

    assert result["outcome"] == "ok"
    assert result["completeness"] == "complete"
    assert result["account_mode"] == "subscription"
    assert result["plan"] is None
    session, weekly = result["windows"]
    assert session["key"] == "session"
    assert session["used_percent"] == pytest.approx(0.0)
    assert session["resets_at"] == pytest.approx(1789935797.0)
    assert session["duration_seconds"] == pytest.approx(18000.0)
    assert session["period_start"] == pytest.approx(1789935797.0 - 18000.0)
    assert weekly["key"] == "weekly"
    assert weekly["resets_at"] == pytest.approx(1789948800.0)
    assert weekly["duration_seconds"] is None
    assert weekly["period_start"] is None
    # ``tier`` is an opaque account id and must never reach the observation.
    assert _LIVE_USAGE["tier"] not in json.dumps(result)


def test_muse_usage_probe_scopes_the_session_to_the_probe_directory(
    tmp_path: Path,
) -> None:
    fake = _make_fake_muse(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _, messages, argv = _run_muse_probe(fake, tmp_path, working_directory=str(scratch))
    assert argv[0]["cwd"] == str(scratch)
    assert messages[2]["params"]["workspaceRoot"] == str(scratch)


def test_muse_usage_probe_preserves_over_quota_percentages(tmp_path: Path) -> None:
    fake = _make_fake_muse(tmp_path)
    over_quota = {
        **_LIVE_USAGE,
        "weekly": {"resetsAtMs": 1789948800000, "usedPercent": 130},
    }
    result, _, _ = _run_muse_probe(fake, tmp_path, usage=over_quota)
    session, weekly = result["windows"]
    assert session["used_percent"] == pytest.approx(0.0)
    assert weekly["used_percent"] == pytest.approx(130.0)


def test_muse_usage_probe_never_minting_host_reports_absence_not_error(
    tmp_path: Path,
) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, _ = _run_muse_probe(
        fake, tmp_path, mode="never_mint", deadline_seconds=2.0
    )
    methods = _methods(messages)
    assert methods[: len(_SEQUENCE_PREFIX)] == _SEQUENCE_PREFIX
    assert methods.count("usage/read") > 1  # it polled until the budget ran out
    assert result["outcome"] == "ok"
    assert result["reason_code"] is None
    assert result["authoritative_empty"] is True
    assert result["completeness"] == "complete"
    assert result["diagnostic"] == "muse_usage_not_yet_observed"
    assert result["windows"] == []


def test_muse_usage_probe_malformed_usage_is_a_structured_error(
    tmp_path: Path,
) -> None:
    fake = _make_fake_muse(tmp_path)
    result, _, _ = _run_muse_probe(fake, tmp_path, usage="not-an-object")
    assert result["outcome"] == "error"
    assert result["reason_code"] == "malformed_payload"
    assert result["diagnostic"] == "muse_usage_malformed"
    assert result["windows"] == []


@pytest.mark.parametrize("mode", ["guard_provider", "guard_model"])
def test_muse_usage_probe_aborts_before_any_turn_when_the_session_is_not_echo(
    tmp_path: Path, mode: str
) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, _ = _run_muse_probe(fake, tmp_path, mode=mode)
    # The frame log is the point: a turn against a real provider would spend
    # tokens on every refresh tick, so no ``turn/start`` may ever be sent.
    assert _methods(messages) == ["initialize", "initialized", "session/start"]
    assert result["outcome"] == "error"
    assert result["reason_code"] == "vendor_drift"
    assert result["diagnostic"] == "muse_echo_session_guard_failed"


def test_muse_usage_probe_session_without_a_session_object_is_malformed(
    tmp_path: Path,
) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, _ = _run_muse_probe(
        fake, tmp_path, mode="session_payload_missing"
    )
    assert "turn/start" not in _methods(messages)
    assert result["outcome"] == "error"
    assert result["reason_code"] == "malformed_payload"
    assert result["diagnostic"] == "muse_session_start_payload_missing"


def test_muse_usage_probe_unexpected_turn_ack_is_vendor_drift(tmp_path: Path) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, _ = _run_muse_probe(fake, tmp_path, mode="turn_ack_queued")
    assert _methods(messages) == _SEQUENCE_PREFIX
    assert result["outcome"] == "error"
    assert result["reason_code"] == "vendor_drift"
    assert result["diagnostic"] == "muse_turn_ack_unexpected"


def test_muse_usage_probe_rejected_turn_is_vendor_drift(tmp_path: Path) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, _ = _run_muse_probe(fake, tmp_path, mode="turn_rejected")
    assert _methods(messages) == _SEQUENCE_PREFIX
    assert result["outcome"] == "error"
    assert result["reason_code"] == "vendor_drift"
    assert result["diagnostic"] == "muse_msp_turn_start_rejected"


def test_muse_usage_probe_missing_usage_method_is_vendor_drift(
    tmp_path: Path,
) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, _ = _run_muse_probe(fake, tmp_path, mode="usage_method_missing")
    assert _methods(messages) == [*_SEQUENCE_PREFIX, "usage/read"]
    assert result["outcome"] == "error"
    assert result["reason_code"] == "vendor_drift"
    assert result["diagnostic"] == "muse_msp_usage_read_rejected"


def test_muse_usage_probe_other_host_errors_are_probe_failures(
    tmp_path: Path,
) -> None:
    fake = _make_fake_muse(tmp_path)
    result, _, _ = _run_muse_probe(fake, tmp_path, mode="usage_read_error")
    assert result["outcome"] == "error"
    assert result["reason_code"] == "probe_failed"
    assert result["diagnostic"] == "muse_msp_usage_read_error"


def test_muse_usage_probe_missing_executable_is_not_installed(tmp_path: Path) -> None:
    result, messages, _ = _run_muse_probe(tmp_path / "no-such-muse", tmp_path)
    assert messages == []
    assert result["outcome"] == "error"
    assert result["reason_code"] == "not_installed"
    assert result["diagnostic"] == "muse_executable_not_found"


def test_muse_usage_probe_refuses_unsolicited_host_requests(tmp_path: Path) -> None:
    fake = _make_fake_muse(tmp_path)
    result, messages, _ = _run_muse_probe(fake, tmp_path, mode="unsolicited_request")
    # The request surfaces while the probe waits on its first ``usage/read``, and
    # an approval-style server request is never answered.
    assert _methods(messages) == [*_SEQUENCE_PREFIX, "usage/read"]
    assert all(message.get("id") != "srv-1" for message in messages)
    assert result["outcome"] == "error"
    assert result["reason_code"] == "probe_failed"
    assert result["diagnostic"] == "muse_msp_unsolicited_request"


def test_muse_usage_probe_unresponsive_host_times_out(tmp_path: Path) -> None:
    fake = _make_fake_muse(tmp_path)
    result, _, _ = _run_muse_probe(fake, tmp_path, mode="hang", deadline_seconds=1.5)
    assert result["outcome"] == "error"
    assert result["reason_code"] == "timeout"


def test_muse_usage_probe_schema_fingerprint_drift_warns_and_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = _make_fake_muse(tmp_path)
    for name, value in _fake_env(tmp_path, fingerprint="sha256:new-release").items():
        monkeypatch.setenv(name, value)
    now = time.time()
    context = default_probe_context(
        "muse", now=now, deadline_seconds=8.0, executable=str(fake)
    )
    with caplog.at_level(logging.WARNING, logger="sase.llm_provider.usage.muse"):
        result = run_usage_probe(
            context, isolate=False, plugin=MuseProvider(), now=now
        ).observation
    assert result is not None
    assert result["outcome"] == "ok"
    assert len(result["windows"]) == 2
    assert "sha256:new-release" in caplog.text


def test_muse_provider_probe_resolves_the_executable_from_sase_muse_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _make_fake_muse(tmp_path)
    for name, value in _fake_env(tmp_path).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SASE_MUSE_PATH", str(fake))
    now = time.time()
    context = default_probe_context("muse", now=now, deadline_seconds=8.0)
    assert context.executable is None
    result = run_usage_probe(
        context, isolate=False, plugin=MuseProvider(), now=now
    ).observation
    assert result is not None
    assert result["outcome"] == "ok"
    assert _read_json_lines(tmp_path / "argv.jsonl")[0]["no_auto_update"] == "1"


def test_muse_absent_ticks_do_not_trip_collector_health_or_render_zero_percent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    from sase.core.rust import require_rust_binding
    from sase.llm_provider.usage.store import (
        load_provider_usage,
        record_provider_usage_observation,
        record_provider_usage_refresh_attempt,
    )

    normalize = require_rust_binding("provider_usage_normalize_muse_usage")
    start = _LIVE_USAGE["observedAtMs"] / 1000.0 + 5.0

    def _tick(payload: dict[str, Any], tick: int) -> float:
        now = start + tick * 300.0
        observation = normalize(
            {
                "schema_version": 1,
                "payload": payload,
                "provider": "muse",
                "context_id": "probe",
                "account_generation": 1,
                "request_started_at": now,
                "now": now,
            }
        )
        record_provider_usage_observation(observation, now=now)
        record_provider_usage_refresh_attempt(
            "muse", "probe", 1, observation["outcome"], now=now
        )
        return now

    _tick({"usage": _LIVE_USAGE}, 0)
    loaded = load_provider_usage(now=start + 1.0)
    assert [w["key"] for w in loaded.snapshot["providers"][0]["windows"]] == [
        "session",
        "weekly",
    ]

    # Three absent ticks would trip USAGE_COLLECTOR_FAILING_THRESHOLD if absence
    # were recorded as an error.
    last = start
    for tick in (1, 2, 3):
        last = _tick({}, tick)
    provider = load_provider_usage(now=last).snapshot["providers"][0]
    assert provider["collection_status"] == "ok"
    assert provider["collector_health"]["state"] == "ok"
    assert provider["collector_health"]["consecutive_failures"] == 0
    # Truthful absence clears the windows; it must never be stored as 0 %.
    assert provider["windows"] == []

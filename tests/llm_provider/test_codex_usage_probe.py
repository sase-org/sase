"""Codex app-server usage collector: handshake, buckets, fencing, cleanup."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from sase.llm_provider.codex import CodexProvider
from sase.llm_provider.usage.codex_collector import collect_codex_usage
from sase.llm_provider.usage.probe import default_probe_context, run_usage_probe
from sase.llm_provider.usage.types import validate_observation

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "usage_probe"
    / "codex_app_server_cli.py"
)
_SECRET_CANARY = "token=SECRET_CANARY_CODEX"
_CODEX_PLUGIN_SPEC = {
    "kind": "import",
    "module": "sase.llm_provider.codex",
    "qualname": "CodexProvider",
}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _context(
    *,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    deadline_seconds: float = 8.0,
    context_id: str = "ctx-1",
    account_generation: int = 1,
):
    # JsonLineSession's deadline is checked against the real wall clock, not
    # an injectable clock, so `now` must track real time here even though
    # the resulting observation's own timestamps stay internally consistent
    # (collect_codex_usage validates against context.request_started_at).
    monkeypatch.setenv("SASE_CODEX_APP_SERVER_MODE", mode)
    return default_probe_context(
        "codex",
        deadline_seconds=deadline_seconds,
        context_id=context_id,
        account_generation=account_generation,
        executable=str(_FIXTURE),
    )


def test_codex_capabilities_are_probe_only() -> None:
    assert CodexProvider().llm_usage_capabilities() == {
        "probe": True,
        "passive_events": False,
    }


def test_multi_bucket_handshake_collects_account_and_unknown_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request_log = tmp_path / "requests.jsonl"
    monkeypatch.setenv("SASE_CODEX_APP_SERVER_REQUEST_LOG", str(request_log))
    context = _context(mode="multi_bucket", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    validate_observation(observation, now=context.request_started_at)

    assert observation["outcome"] == "ok"
    assert observation["completeness"] == "complete"
    assert observation["account_mode"] == "subscription"
    assert observation["plan"] == "pro"
    by_key = {window["key"]: window for window in observation["windows"]}
    assert set(by_key) == {
        "codex:primary",
        "codex:secondary",
        "codex_bengalfox:primary",
        "codex_bengalfox:secondary",
    }
    assert by_key["codex:primary"]["applicability"] == {"kind": "account"}
    assert by_key["codex:primary"]["used_percent"] == 61.0
    assert by_key["codex:primary"]["vendor_state"] == "allowed"
    assert by_key["codex:secondary"]["used_percent"] == 12.0
    unknown = by_key["codex_bengalfox:primary"]["applicability"]
    assert unknown == {
        "kind": "unknown",
        "vendor_label": "GPT-5.3-Codex-Spark",
        "vendor_id": "codex_bengalfox",
    }
    assert by_key["codex_bengalfox:primary"]["label"] == "GPT-5.3-Codex-Spark"
    rate_limit_requests = [
        request
        for request in _read_jsonl(request_log)
        if request.get("method") == "account/rateLimits/read"
    ]
    assert len(rate_limit_requests) == 1
    assert "params" not in rate_limit_requests[0]


def test_rate_limits_retries_with_legacy_params_when_paramless_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.WARNING,
        logger="sase.llm_provider.usage.codex_collector",
    )
    request_log = tmp_path / "requests.jsonl"
    monkeypatch.setenv("SASE_CODEX_APP_SERVER_REQUEST_LOG", str(request_log))
    context = _context(mode="legacy_params_required", monkeypatch=monkeypatch)

    observation = collect_codex_usage(context)

    validate_observation(observation, now=context.request_started_at)
    assert observation["outcome"] == "ok"
    assert observation["windows"]
    assert "primary no_params failed" in observation["diagnostic"]
    assert "recovered via legacy_params" in observation["diagnostic"]
    assert "usage probe strategy recovered codex drift" in caplog.text
    rate_limit_requests = [
        request
        for request in _read_jsonl(request_log)
        if request.get("method") == "account/rateLimits/read"
    ]
    assert len(rate_limit_requests) == 2
    assert "params" not in rate_limit_requests[0]
    assert rate_limit_requests[1]["params"] == {"excludeResetCreditDetails": True}


def test_legacy_single_bucket_without_by_limit_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="legacy", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    validate_observation(observation, now=context.request_started_at)

    assert observation["outcome"] == "ok"
    keys = {window["key"] for window in observation["windows"]}
    assert keys == {"codex:primary"}


def test_null_windows_are_treated_as_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(mode="null_fields", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "parse_error"
    assert observation["windows"] == []


def test_reached_type_marks_window_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(mode="reached", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    validate_observation(observation, now=context.request_started_at)
    window = observation["windows"][0]
    assert window["vendor_state"] == "rejected"
    assert window["used_percent"] == 100.0


def test_account_read_api_mode_is_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="api_mode", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "not_applicable"
    assert observation["reason_code"] == "api_mode"
    assert observation["windows"] == []


def test_account_read_error_does_not_block_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="account_read_method_missing", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "ok"
    assert observation["windows"]


def test_account_read_unauthenticated_response_is_inconclusive_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="account_read_unauthenticated", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "ok"


def test_unauthenticated_rate_limits_error_maps_to_logged_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="unauthenticated", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "unauthenticated"
    assert observation["reason_code"] == "logged_out"
    assert observation["windows"] == []


def test_method_not_found_on_rate_limits_is_vendor_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request_log = tmp_path / "requests.jsonl"
    monkeypatch.setenv("SASE_CODEX_APP_SERVER_REQUEST_LOG", str(request_log))
    context = _context(mode="method_not_found", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "vendor_drift"
    assert "method not found" in observation["diagnostic"]
    rate_limit_requests = [
        request
        for request in _read_jsonl(request_log)
        if request.get("method") == "account/rateLimits/read"
    ]
    assert len(rate_limit_requests) == 2


def test_malformed_rate_limits_result_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="malformed", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "malformed_payload"


def test_rate_limits_rpc_error_carries_bounded_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="rate_limits_rpc_error", monkeypatch=monkeypatch)

    observation = collect_codex_usage(context)

    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "probe_failed"
    diagnostic = observation["diagnostic"]
    assert "app-server account/rateLimits/read error -32042" in diagnostic
    assert "Vendor drift details" in diagnostic
    assert "\n" not in diagnostic
    assert len(diagnostic) <= 200


def test_notify_then_reply_skips_unrelated_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="notify_then_reply", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "ok"
    assert observation["windows"]


def test_secret_canary_on_stderr_is_not_in_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(mode="secret_stderr", monkeypatch=monkeypatch)
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "ok"
    assert _SECRET_CANARY not in str(observation)


def test_hang_before_initialize_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(
        mode="hang_before_initialize", monkeypatch=monkeypatch, deadline_seconds=1.5
    )
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "timeout"


def test_hang_on_rate_limits_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(
        mode="hang_on_rate_limits", monkeypatch=monkeypatch, deadline_seconds=1.5
    )
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "timeout"


def test_descendant_processes_are_reaped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pidfile = tmp_path / "child.pid"
    monkeypatch.setenv("SASE_CODEX_APP_SERVER_PIDFILE", str(pidfile))
    context = _context(
        mode="descendants", monkeypatch=monkeypatch, deadline_seconds=1.5
    )
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "timeout"
    child_pid = int(pidfile.read_text(encoding="utf-8"))
    assert not _pid_alive(child_pid)


def test_executable_not_found_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_CODEX_APP_SERVER_MODE", "multi_bucket")
    context = default_probe_context(
        "codex",
        executable="/nonexistent/sase-codex-usage-test-binary",
    )
    observation = collect_codex_usage(context)
    assert observation["outcome"] == "unsupported"
    assert observation["reason_code"] == "not_installed"


def test_account_fencing_preserves_caller_supplied_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _context(
        mode="multi_bucket",
        monkeypatch=monkeypatch,
        context_id="ctx-alpha",
        account_generation=1,
    )
    second = _context(
        mode="multi_bucket",
        monkeypatch=monkeypatch,
        context_id="ctx-beta",
        account_generation=2,
    )
    first_observation = collect_codex_usage(first)
    second_observation = collect_codex_usage(second)

    assert first_observation["context_id"] == "ctx-alpha"
    assert first_observation["account_generation"] == 1
    assert second_observation["context_id"] == "ctx-beta"
    assert second_observation["account_generation"] == 2


def test_registered_hook_runs_through_isolated_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    monkeypatch.setenv("SASE_CODEX_APP_SERVER_MODE", "multi_bucket")
    monkeypatch.setenv("SASE_CODEX_PATH", str(_FIXTURE))
    context = default_probe_context("codex", deadline_seconds=8)
    result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec=_CODEX_PLUGIN_SPEC,
    )
    assert result.skipped is None
    assert result.observation is not None
    assert result.observation["provider"] == "codex"
    assert result.observation["outcome"] == "ok"
    assert result.observation["windows"]

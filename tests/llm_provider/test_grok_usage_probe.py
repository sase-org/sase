"""Grok Build ACP billing collector: identity, wire name, decode, cleanup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.llm_provider.grok import GrokProvider
from sase.llm_provider.usage.probe import default_probe_context, run_usage_probe

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "usage_probe" / "grok_acp_cli.py"
)
_NATIVE_VERSION = "grok 1.0.13 (72a61251fc) [stable]"


def _make_fake_grok(tmp_path: Path) -> Path:
    path = tmp_path / "grok"
    shutil.copy(_FIXTURE, path)
    path.chmod(0o755)
    return path


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _run_grok_probe(
    fake_grok: Path,
    tmp_path: Path,
    payload: dict[str, Any] | None = None,
    *,
    mode: str = "native",
    version: str = _NATIVE_VERSION,
    deadline_seconds: float = 5.0,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[list[str]]]:
    messages_path = tmp_path / "messages.jsonl"
    argv_path = tmp_path / "argv.jsonl"
    env = {
        "SASE_FAKE_GROK_MODE": mode,
        "SASE_FAKE_GROK_VERSION": version,
        "SASE_FAKE_GROK_MESSAGES": str(messages_path),
        "SASE_FAKE_GROK_ARGV": str(argv_path),
    }
    if payload is not None:
        env["SASE_FAKE_GROK_BILLING"] = json.dumps(payload)
    now = time.time()
    context = default_probe_context(
        "grok",
        now=now,
        deadline_seconds=deadline_seconds,
        executable=str(fake_grok),
    )
    probe_result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec={"kind": "entry_point", "name": "grok"},
        now=now,
        env=env,
    )
    result = probe_result.observation
    assert result is not None
    return result, _read_json_lines(messages_path), _read_json_lines(argv_path)


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


def test_grok_provider_declares_usage_probe_capability() -> None:
    assert GrokProvider().llm_usage_capabilities() == {
        "probe": True,
        "passive_events": False,
    }


def test_grok_usage_probe_collects_native_weekly_billing(tmp_path: Path) -> None:
    fake = _make_fake_grok(tmp_path)
    payload = {
        "config": {
            "creditUsagePercent": 37.5,
            "currentPeriod": {
                "type": "USAGE_PERIOD_TYPE_WEEKLY",
                "start": "2027-01-15T00:00:00Z",
                "end": "2027-01-22T00:00:00Z",
            },
            "monthlyLimit": {"val": 1000},
            "used": 900,
            "onDemandEnabled": True,
            "prepaidBalance": 1234,
            "history": [{"amount": 1}],
            "subscriptionTier": "SuperGrok Heavy",
        }
    }
    result, messages, argv = _run_grok_probe(fake, tmp_path, payload)
    window = result["windows"][0]
    assert result["outcome"] == "ok"
    assert result["account_mode"] == "subscription"
    assert result["plan"] == "SuperGrok Heavy"
    assert result["completeness"] == "complete"
    assert result["diagnostic"] == "grok_build_billing_first_party_unstable"
    assert window["key"] == "included_weekly"
    assert window["label"] == "Grok included weekly allowance"
    assert window["used_percent"] == pytest.approx(37.5)
    assert window["resets_at"] == pytest.approx(_epoch("2027-01-22T00:00:00Z"))
    assert window["period_start"] == pytest.approx(_epoch("2027-01-15T00:00:00Z"))
    assert window["duration_seconds"] == pytest.approx(604800.0)
    assert window["applicability"] == {"kind": "account"}
    assert window["vendor_state"] == "unknown"
    assert [message["method"] for message in messages] == [
        "initialize",
        "_x.ai/billing",
    ]
    encoded_result = json.dumps(result)
    assert "onDemand" not in encoded_result
    assert "prepaid" not in encoded_result
    assert ["--version"] in argv
    assert ["--no-auto-update", "agent", "stdio"] in argv


def test_grok_usage_probe_decodes_verified_legacy_monthly_ratio(
    tmp_path: Path,
) -> None:
    fake = _make_fake_grok(tmp_path)
    payload = {
        "config": {
            "monthlyLimit": {"val": 2000},
            "used": {"val": 500},
            "billingPeriodStart": "2027-01-01T00:00:00Z",
            "billingPeriodEnd": "2027-02-01T00:00:00Z",
            "subscriptionTier": "SuperGrok",
        }
    }
    result, _, _ = _run_grok_probe(fake, tmp_path, payload)
    window = result["windows"][0]
    assert result["outcome"] == "ok"
    assert window["key"] == "included_monthly"
    assert window["label"] == "Grok included monthly allowance"
    assert window["used_percent"] == pytest.approx(25.0)
    assert window["resets_at"] == pytest.approx(_epoch("2027-02-01T00:00:00Z"))


def test_grok_usage_probe_missing_billing_method_is_vendor_drift(
    tmp_path: Path,
) -> None:
    fake = _make_fake_grok(tmp_path)
    result, messages, _ = _run_grok_probe(fake, tmp_path, mode="method_missing")
    assert result["outcome"] == "error"
    assert result["reason_code"] == "vendor_drift"
    assert result["diagnostic"] == "grok_billing_extension_missing"
    assert [message["method"] for message in messages] == [
        "initialize",
        "_x.ai/billing",
    ]


def test_grok_usage_probe_auth_required_is_unauthenticated(tmp_path: Path) -> None:
    fake = _make_fake_grok(tmp_path)
    result, _ = _run_grok_probe(fake, tmp_path, mode="auth_required")[:2]
    assert result["outcome"] == "unauthenticated"
    assert result["reason_code"] == "logged_out"


@pytest.mark.parametrize("tier", ["Free", "Enterprise"])
def test_grok_usage_probe_explicit_ineligible_accounts_are_not_applicable(
    tmp_path: Path, tier: str
) -> None:
    fake = _make_fake_grok(tmp_path)
    payload = {"config": None, "subscriptionTier": tier}
    result, _ = _run_grok_probe(fake, tmp_path, payload)[:2]
    assert result["outcome"] == "not_applicable"
    assert result["reason_code"] is None


def test_grok_usage_probe_api_auth_evidence_is_not_applicable(
    tmp_path: Path,
) -> None:
    fake = _make_fake_grok(tmp_path)
    payload = {"config": None, "authMode": "api_key"}
    result, _ = _run_grok_probe(fake, tmp_path, payload)[:2]
    assert result["outcome"] == "not_applicable"
    assert result["reason_code"] == "api_mode"


def test_grok_usage_probe_absent_config_without_evidence_is_malformed(
    tmp_path: Path,
) -> None:
    fake = _make_fake_grok(tmp_path)
    result, _ = _run_grok_probe(fake, tmp_path, {"config": None})[:2]
    assert result["outcome"] == "error"
    assert result["reason_code"] == "malformed_payload"


def test_grok_usage_probe_identity_mismatch_is_unsupported(tmp_path: Path) -> None:
    fake = _make_fake_grok(tmp_path)
    result, messages, argv = _run_grok_probe(
        fake, tmp_path, {"config": None}, version="not-grok 0.1.0"
    )
    assert result["outcome"] == "unsupported"
    assert result["reason_code"] == "unsupported_cli_version"
    assert messages == []
    assert argv == [["--version"]]


def test_grok_usage_probe_missing_period_is_partial(tmp_path: Path) -> None:
    fake = _make_fake_grok(tmp_path)
    payload = {
        "config": {
            "creditUsagePercent": 12.0,
            "subscriptionTier": "SuperGrok",
        }
    }
    result, _ = _run_grok_probe(fake, tmp_path, payload)[:2]
    window = result["windows"][0]
    assert result["outcome"] == "ok"
    assert result["completeness"] == "partial"
    assert result["diagnostic"] == "grok_billing_period_missing_reset"
    assert window["key"] == "included"
    assert window["resets_at"] is None
    assert window["duration_seconds"] is None


def test_grok_usage_probe_missing_percentage_is_malformed(tmp_path: Path) -> None:
    fake = _make_fake_grok(tmp_path)
    payload = {
        "config": {
            "currentPeriod": {
                "type": "USAGE_PERIOD_TYPE_WEEKLY",
                "start": "2027-01-15T00:00:00Z",
                "end": "2027-01-22T00:00:00Z",
            }
        }
    }
    result, _ = _run_grok_probe(fake, tmp_path, payload)[:2]
    assert result["outcome"] == "error"
    assert result["reason_code"] == "malformed_payload"


def test_grok_usage_probe_reaps_descendant_processes(tmp_path: Path) -> None:
    fake = _make_fake_grok(tmp_path)
    pidfile = tmp_path / "child.pid"
    env = {
        "SASE_FAKE_GROK_MODE": "descendants",
        "SASE_FAKE_GROK_CHILD_PID": str(pidfile),
    }
    now = time.time()
    context = default_probe_context(
        "grok", now=now, deadline_seconds=3.0, executable=str(fake)
    )
    probe_result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec={"kind": "entry_point", "name": "grok"},
        now=now,
        env=env,
    )
    result = probe_result.observation
    assert result is not None
    assert result["outcome"] == "error"
    assert result["reason_code"] == "timeout"
    deadline = time.time() + 2.0
    pid_text = ""
    while time.time() < deadline:
        if pidfile.exists():
            pid_text = pidfile.read_text(encoding="utf-8").strip()
            if pid_text:
                break
        time.sleep(0.05)  # sase-test-wait: pidfile from descendant grok child
    assert pid_text
    child_pid = int(pid_text)
    assert not _pid_alive(child_pid)

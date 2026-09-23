"""Adaptive admission: floors, fingerprints, and mark-only limit events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.llm_provider._registry_metadata import _usage_capabilities


def _observation(
    provider: str, *, at: float, used_percent: float = 10.0, reset_at: float
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": provider,
        "context_id": "default",
        "account_generation": 1,
        "ordering_token": at,
        "received_at": at,
        "source": "probe",
        "outcome": "ok",
        "reason_code": None,
        "diagnostic": None,
        "completeness": "complete",
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": "synthetic",
        "windows": [
            {
                "key": "default",
                "label": "Synthetic default",
                "used_percent": used_percent,
                "resets_at": reset_at,
                "duration_seconds": None,
                "period_start": None,
                "applicability": {"kind": "account"},
                "observed_at": at,
                "source": "probe",
                "vendor_state": "allowed",
            }
        ],
    }


def test_plugin_floors_declared() -> None:
    from sase.llm_provider.agy import AgyProvider
    from sase.llm_provider.claude import ClaudeCodeProvider
    from sase.llm_provider.codex import CodexProvider
    from sase.llm_provider.grok import GrokProvider
    from sase.llm_provider.muse import MuseProvider

    assert (
        ClaudeCodeProvider().llm_usage_capabilities()["min_probe_interval_seconds"]
        == 300
    )
    assert MuseProvider().llm_usage_capabilities()["min_probe_interval_seconds"] == 180
    for provider in (AgyProvider(), GrokProvider(), CodexProvider()):
        assert provider.llm_usage_capabilities()["min_probe_interval_seconds"] == 120


def test_usage_capabilities_drops_invalid_floor() -> None:
    assert (
        _usage_capabilities({"probe": True, "min_probe_interval_seconds": 300})[
            "min_probe_interval_seconds"
        ]
        == 300.0
    )
    for bad in (None, True, "300", float("nan"), float("inf"), 59.9, 86_400.1):
        assert "min_probe_interval_seconds" not in _usage_capabilities(
            {"probe": True, "min_probe_interval_seconds": bad}
        )
    # probe flag still normalizes when the floor is dropped.
    assert (
        _usage_capabilities({"probe": True, "min_probe_interval_seconds": 10})["probe"]
        is True
    )


def test_admit_one_passes_adaptive_floor_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage import refresh as refresh_mod
    from tests.llm_provider._provider_config_helpers import mock_provider_config

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    monkeypatch.setattr(refresh_mod, "usage_probe_floor", lambda _p: 300.0)
    monkeypatch.setattr(refresh_mod, "usage_cli_fingerprint", lambda _p: "fp-1")

    seen: dict[str, dict[str, Any]] = {}

    def fake_due(*args: object, **kwargs: object):
        seen["due"] = dict(kwargs)

        class _Due:
            due = True

        return _Due()

    def fake_admit(*args: object, **kwargs: object):
        seen["admit"] = dict(kwargs)

        class _Reservation:
            operation_id = "op-1"
            lease_id = "lease-1"

        class _Admitted:
            status = "reserved"
            reason = "never_observed"
            due_at = None
            reservation = _Reservation()

        return _Admitted()

    monkeypatch.setattr(refresh_mod, "evaluate_provider_usage_refresh_due", fake_due)
    monkeypatch.setattr(refresh_mod, "admit_provider_usage_refresh", fake_admit)
    monkeypatch.setattr(
        refresh_mod,
        "prepare_provider_usage_account_context",
        lambda provider, context_id, **_kw: type(
            "Ctx", (), {"context_id": context_id, "account_generation": 1}
        )(),
    )
    refresh_mod._admit_one(
        "claude", operation_id="op-1", explicit=False, cadence_seconds=300.0, now=None
    )
    assert seen["due"]["adaptive"] is True
    assert seen["due"]["min_interval_seconds"] == 300.0
    assert seen["due"]["cli_fingerprint"] == "fp-1"
    assert seen["admit"]["adaptive"] is True
    assert seen["admit"]["min_interval_seconds"] == 300.0
    assert seen["admit"]["cli_fingerprint"] == "fp-1"


def test_runner_finish_passes_floor_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.usage import refresh_runner

    seen: dict[str, Any] = {}

    def fake_record(*args: object, **kwargs: object):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(
        refresh_runner, "record_provider_usage_refresh_attempt", fake_record
    )
    monkeypatch.setattr(
        refresh_runner, "release_provider_usage_refresh", lambda *a, **k: True
    )
    job = {
        "provider": "claude",
        "context_id": "default",
        "account_generation": 1,
        "lease_id": "lease-1",
        "min_interval_seconds": 300.0,
        "cli_fingerprint": "fp-1",
    }
    refresh_runner._finish_job(job, "ok", 300.0, 1_800_000_000.0)
    assert seen["adaptive"] is True
    assert seen["min_interval_seconds"] == 300.0
    assert seen["cli_fingerprint"] == "fp-1"


def test_cli_fingerprint_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.llm_provider.usage import _probe_meta

    exe = tmp_path / "claude"
    exe.write_bytes(b"#!/bin/sh\necho hi\n")
    monkeypatch.setattr(
        _probe_meta, "resolve_provider_cli_command", lambda _p: str(exe)
    )
    stat = exe.stat()
    assert _probe_meta.usage_cli_fingerprint("claude") == (
        f"{exe}:{stat.st_mtime_ns}:{stat.st_size}"
    )
    monkeypatch.setattr(_probe_meta, "resolve_provider_cli_command", lambda _p: "")
    assert _probe_meta.usage_cli_fingerprint("claude") is None
    monkeypatch.setattr(
        _probe_meta, "resolve_provider_cli_command", lambda _p: "does-not-exist-xyz"
    )
    assert _probe_meta.usage_cli_fingerprint("claude") is None


def test_claude_floor_blocks_marked_due(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage.store import (
        admit_provider_usage_refresh,
        evaluate_provider_usage_refresh_due,
        mark_provider_usage_refresh_due,
        prepare_provider_usage_account_context,
    )
    from tests.llm_provider._provider_config_helpers import mock_provider_config

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    now = 1_800_000_000.0
    context = prepare_provider_usage_account_context("claude", "default", now=now)
    admitted = admit_provider_usage_refresh(
        "claude",
        context.context_id,
        context.account_generation,
        "op-floor",
        75.0,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=300.0,
        cli_fingerprint="fp-1",
        now=now,
    )
    assert admitted.status == "reserved"
    mark_provider_usage_refresh_due(
        "claude",
        context.context_id,
        context.account_generation,
        "limit_event",
        now=now + 1.0,
    )
    deferred = evaluate_provider_usage_refresh_due(
        "claude",
        context.context_id,
        context.account_generation,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=300.0,
        cli_fingerprint="fp-1",
        now=now + 10.0,
    )
    assert deferred.due is False
    assert deferred.reason == "floor"
    assert deferred.due_at == pytest.approx(now + 300.0)
    # After the floor passes the mark is honored.
    due = evaluate_provider_usage_refresh_due(
        "claude",
        context.context_id,
        context.account_generation,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=300.0,
        cli_fingerprint="fp-1",
        now=now + 301.0,
    )
    assert due.due is True
    assert due.reason == "marked_due"


def test_explicit_bypasses_floor_but_respects_cooldown_and_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage.store import (
        admit_provider_usage_refresh,
        evaluate_provider_usage_refresh_due,
        prepare_provider_usage_account_context,
        record_provider_usage_refresh_attempt,
    )
    from tests.llm_provider._provider_config_helpers import mock_provider_config

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    now = 1_800_000_000.0
    context = prepare_provider_usage_account_context("muse", "default", now=now)
    admit_provider_usage_refresh(
        "muse",
        context.context_id,
        context.account_generation,
        "op-exp",
        75.0,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=180.0,
        now=now,
    )
    # Explicit bypasses the floor before any attempt recorded a cooldown.
    bypass = evaluate_provider_usage_refresh_due(
        "muse",
        context.context_id,
        context.account_generation,
        cadence_seconds=300.0,
        explicit=True,
        adaptive=True,
        min_interval_seconds=180.0,
        now=now + 10.0,
    )
    assert bypass.due is True
    assert bypass.reason == "explicit"
    record_provider_usage_refresh_attempt(
        "muse",
        context.context_id,
        context.account_generation,
        "ok",
        cadence_seconds=300.0,
        adaptive=True,
        min_interval_seconds=180.0,
        now=now + 10.0,
    )
    cooled = evaluate_provider_usage_refresh_due(
        "muse",
        context.context_id,
        context.account_generation,
        cadence_seconds=300.0,
        explicit=True,
        adaptive=True,
        min_interval_seconds=180.0,
        now=now + 20.0,
    )
    assert cooled.due is False
    assert cooled.reason == "cooldown"
    record_provider_usage_refresh_attempt(
        "muse",
        context.context_id,
        context.account_generation,
        "error",
        cadence_seconds=300.0,
        reason_code="rate_limited",
        retry_after_seconds=3600.0,
        adaptive=True,
        min_interval_seconds=180.0,
        now=now + 80.0,
    )
    limited = evaluate_provider_usage_refresh_due(
        "muse",
        context.context_id,
        context.account_generation,
        cadence_seconds=300.0,
        explicit=True,
        adaptive=True,
        min_interval_seconds=180.0,
        now=now + 90.0,
    )
    assert limited.due is False
    assert limited.reason == "retry_after"


def test_parked_unparks_on_fingerprint_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage.store import (
        evaluate_provider_usage_refresh_due,
        prepare_provider_usage_account_context,
        record_provider_usage_refresh_attempt,
    )
    from tests.llm_provider._provider_config_helpers import mock_provider_config

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    now = 1_800_000_000.0
    context = prepare_provider_usage_account_context("agy", "default", now=now)
    record_provider_usage_refresh_attempt(
        "agy",
        context.context_id,
        context.account_generation,
        "unsupported",
        cadence_seconds=300.0,
        reason_code="not_installed",
        cli_fingerprint="fp-1",
        adaptive=True,
        now=now,
    )
    parked = evaluate_provider_usage_refresh_due(
        "agy",
        context.context_id,
        context.account_generation,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        cli_fingerprint="fp-1",
        now=now + 10.0,
    )
    assert parked.due is False
    assert parked.reason == "parked"
    unparked = evaluate_provider_usage_refresh_due(
        "agy",
        context.context_id,
        context.account_generation,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        cli_fingerprint="fp-2",
        now=now + 10.0,
    )
    assert unparked.due is True
    assert unparked.reason == "cli_changed"


def test_limit_event_spawns_no_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage import refresh as refresh_mod
    from tests.llm_provider._provider_config_helpers import mock_provider_config

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    monkeypatch.setattr(
        "sase.procs.submit_proc_request",
        lambda request: pytest.fail("limit event submitted a probe"),
    )
    assert (
        refresh_mod.trigger_usage_refresh_after_limit_event(
            "synth", now=1_800_000_000.0
        )
        is None
    )


def test_floor_aware_freshness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage.store import (
        load_provider_usage,
        record_provider_usage_observation,
    )
    from tests.llm_provider._provider_config_helpers import mock_provider_config

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    now = 1_800_000_000.0
    record_provider_usage_observation(
        _observation("synth", at=now, reset_at=now + 3600.0), now=now
    )
    # Freshness uses max(cadence, floor): at +300 s a 120 s cadence alone is
    # stale (fresh until 240 s) while a 300 s floor stays fresh (until 600 s).
    floored = load_provider_usage(
        now=now + 300.0,
        cadence_seconds=120.0,
        provider_min_intervals={"synth": 300.0},
    )
    entry = next(
        item for item in floored.snapshot["providers"] if item["provider"] == "synth"
    )
    assert entry["windows"][0]["freshness"] == "fresh"
    legacy = load_provider_usage(
        now=now + 300.0,
        cadence_seconds=120.0,
        provider_min_intervals={},
    )
    legacy_entry = next(
        item for item in legacy.snapshot["providers"] if item["provider"] == "synth"
    )
    assert legacy_entry["windows"][0]["freshness"] == "stale"

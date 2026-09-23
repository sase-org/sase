"""Shared usage-refresh service: admission, coalescing, opt-out, and triggers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.llm_provider.usage.refresh import (
    USAGE_REFRESH_OPERATION,
    request_due_usage_refresh,
    submit_usage_refresh,
    trigger_usage_refresh_after_limit_event,
)
from sase.llm_provider.usage.store import (
    ProviderUsageAccountContext,
    ProviderUsageRefreshAdmitOutcome,
    ProviderUsageRefreshDueOutcome,
    ProviderUsageRefreshMarkDueOutcome,
    ProviderUsageRefreshReservation,
    evaluate_provider_usage_refresh_due,
    record_provider_usage_observation,
    record_provider_usage_refresh_attempt,
)
from sase.procs import ProcSubmitRequest
from sase.testing.usage_synthetic import SYNTHETIC_PLUGIN_SPEC
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _reservation(
    provider: str, operation_id: str, *, now: float = 1_800_000_000.0
) -> ProviderUsageRefreshReservation:
    return ProviderUsageRefreshReservation(
        version=1,
        provider=provider,
        context_id="default",
        account_generation=1,
        operation_id=operation_id,
        lease_id=f"lease-{provider}",
        reserved_at=now,
        expires_at=now + 45.0,
    )


def _admit_state() -> dict[tuple[str, str, int], ProviderUsageRefreshReservation]:
    return {}


def _usage_observation(
    provider: str,
    *,
    at: float,
    used_percent: float,
    reset_at: float,
    vendor_state: str = "allowed",
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
                "vendor_state": vendor_state,
            }
        ],
    }


@pytest.fixture
def usage_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict[str, object]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    reserved = _admit_state()

    def prepare(provider: str, context_id: str, *, now: float | None = None):
        return ProviderUsageAccountContext(
            version=1,
            provider=provider,
            context_id=context_id,
            account_generation=1,
            changed=False,
        )

    def admit(
        provider: str,
        context_id: str,
        account_generation: int,
        operation_id: str,
        ttl_seconds: float,
        *,
        cadence_seconds: float = 300.0,
        explicit: bool = False,
        now: float | None = None,
        adaptive: bool = False,
        min_interval_seconds: float | None = None,
        cli_fingerprint: str | None = None,
        active_cadence_seconds: float | None = None,
        warn_percent: float | None = None,
    ) -> ProviderUsageRefreshAdmitOutcome:
        key = (provider, context_id, account_generation)
        existing = reserved.get(key)
        clock = 1_800_000_000.0 if now is None else now
        if existing is not None:
            return ProviderUsageRefreshAdmitOutcome(
                version=1,
                status="joined",
                reason="joined",
                due_at=None,
                reservation=existing,
            )
        reservation = _reservation(provider, operation_id, now=clock)
        reserved[key] = reservation
        return ProviderUsageRefreshAdmitOutcome(
            version=1,
            status="reserved",
            reason="never_observed",
            due_at=None,
            reservation=reservation,
        )

    def due(*args: object, **kwargs: object) -> ProviderUsageRefreshDueOutcome:
        return ProviderUsageRefreshDueOutcome(
            version=1, due=True, reason="never_observed", due_at=None
        )

    def mark(*args: object, **kwargs: object) -> ProviderUsageRefreshMarkDueOutcome:
        return ProviderUsageRefreshMarkDueOutcome(
            version=1, marked=True, due_at=1_800_000_000.0, reason="limit_event"
        )

    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.prepare_provider_usage_account_context",
        prepare,
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.admit_provider_usage_refresh", admit
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.evaluate_provider_usage_refresh_due",
        due,
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.mark_provider_usage_refresh_due", mark
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.release_provider_usage_refresh",
        lambda *args, **kwargs: True,
    )
    return {"reserved": reserved}


def test_submit_coalesces_overlapping_provider_subsets(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted: list[ProcSubmitRequest] = []

    def fake_submit(request: ProcSubmitRequest) -> SimpleNamespace:
        submitted.append(request)
        return SimpleNamespace(proc_id=request.proc_id)

    monkeypatch.setattr("sase.procs.submit_proc_request", fake_submit)
    specs = {"synth": SYNTHETIC_PLUGIN_SPEC, "other": SYNTHETIC_PLUGIN_SPEC}
    first = submit_usage_refresh(
        ("synth", "other"),
        explicit=True,
        origin="cli",
        plugin_specs=specs,
    )
    second = submit_usage_refresh(
        ("synth",),
        explicit=True,
        origin="ace",
        plugin_specs=specs,
    )
    assert len(submitted) == 1
    assert submitted[0].operation == USAGE_REFRESH_OPERATION
    assert set(first.operation_ids) == {submitted[0].proc_id}
    assert {item.provider: item.status for item in first.providers} == {
        "synth": "reserved",
        "other": "reserved",
    }
    assert {item.provider: item.status for item in second.providers} == {
        "synth": "joined",
    }
    assert second.operation_ids == first.operation_ids
    payload_providers = [
        item["provider"] for item in submitted[0].operation_payload["providers"]
    ]
    assert payload_providers == ["synth", "other"]


def test_joining_one_provider_does_not_drop_a_new_peer(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted: list[ProcSubmitRequest] = []

    def fake_submit(request: ProcSubmitRequest) -> SimpleNamespace:
        submitted.append(request)
        return SimpleNamespace(proc_id=request.proc_id)

    monkeypatch.setattr("sase.procs.submit_proc_request", fake_submit)
    specs = {"synth": SYNTHETIC_PLUGIN_SPEC, "other": SYNTHETIC_PLUGIN_SPEC}
    submit_usage_refresh(
        ("synth",),
        explicit=True,
        origin="axe",
        plugin_specs=specs,
    )
    receipt = submit_usage_refresh(
        ("synth", "other"),
        explicit=True,
        origin="cli",
        plugin_specs=specs,
    )
    assert len(submitted) == 2
    by_provider = {item.provider: item.status for item in receipt.providers}
    assert by_provider["synth"] == "joined"
    assert by_provider["other"] == "reserved"
    assert submitted[1].operation_payload["providers"][0]["provider"] == "other"


def test_config_opt_out_does_not_submit(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.procs.submit_proc_request",
        lambda request: pytest.fail("opt-out submitted a proc"),
    )
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": False}})
    receipt = submit_usage_refresh(("synth",), explicit=True, origin="cli")
    assert receipt.providers[0].status == "disabled"
    assert receipt.providers[0].reason == "config_disabled"
    assert receipt.operation_ids == ()


def test_limit_event_trigger_marks_due_and_submits(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted: list[ProcSubmitRequest] = []
    monkeypatch.setattr(
        "sase.procs.submit_proc_request",
        lambda request: (
            submitted.append(request) or SimpleNamespace(proc_id=request.proc_id)
        ),
    )
    marked: list[tuple[str, str]] = []
    import sase.llm_provider.usage.refresh as refresh_mod

    real_mark = refresh_mod._mark_usage_refresh_due

    def _capture_mark(provider: str, reason: str, **kwargs: object) -> None:
        marked.append((provider, reason))
        return real_mark(provider, reason, **kwargs)

    monkeypatch.setattr(refresh_mod, "_mark_usage_refresh_due", _capture_mark)
    receipt = trigger_usage_refresh_after_limit_event(
        "synth", expires_at=1_800_000_100.0
    )
    assert receipt is None
    assert submitted == []
    assert ("synth", "limit_event") in marked
    assert ("synth", "disable_expiry") in marked


def test_limit_event_future_expiry_does_not_block_next_cadence(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})

    submitted: list[ProcSubmitRequest] = []
    monkeypatch.setattr(
        "sase.procs.submit_proc_request",
        lambda request: (
            submitted.append(request) or SimpleNamespace(proc_id=request.proc_id)
        ),
    )

    limit_now = 1_800_000_000.0
    reset_now = limit_now + 600.0
    disable_expiry = reset_now + 4.0 * 24.0 * 60.0 * 60.0
    record_provider_usage_observation(
        _usage_observation(
            "synth",
            at=limit_now,
            used_percent=100.0,
            reset_at=reset_now,
            vendor_state="rejected",
        ),
        now=limit_now,
    )

    trigger_receipt = trigger_usage_refresh_after_limit_event(
        "synth", expires_at=disable_expiry, now=limit_now
    )
    assert trigger_receipt is None
    assert submitted == []

    record_provider_usage_observation(
        _usage_observation(
            "synth",
            at=reset_now,
            used_percent=7.0,
            reset_at=disable_expiry + 7.0 * 24.0 * 60.0 * 60.0,
        ),
        now=reset_now,
    )
    schedule = record_provider_usage_refresh_attempt(
        "synth",
        "default",
        1,
        "ok",
        cadence_seconds=300.0,
        now=reset_now,
    )
    assert schedule["due_at"] == pytest.approx(disable_expiry)
    assert schedule["due_reason"] == "disable_expiry"

    fresh = evaluate_provider_usage_refresh_due(
        "synth",
        "default",
        1,
        cadence_seconds=300.0,
        explicit=False,
        now=reset_now + 10.0,
    )
    assert fresh.due is False
    assert fresh.reason == "fresh"
    assert fresh.due_at == pytest.approx(reset_now + 300.0)

    due = evaluate_provider_usage_refresh_due(
        "synth",
        "default",
        1,
        cadence_seconds=300.0,
        explicit=False,
        now=reset_now + 300.0,
    )
    assert due.due is True
    assert due.reason == "cadence"

    # The shared submit path is adaptive and jitters cadence by ±10%, so
    # advance past the jitter band to assert the automatic pickup.
    automatic_receipt = submit_usage_refresh(
        ("synth",),
        explicit=False,
        origin="axe",
        now=reset_now + 330.0,
        plugin_specs={"synth": SYNTHETIC_PLUGIN_SPEC},
    )
    assert automatic_receipt.providers[0].status == "reserved"
    assert automatic_receipt.providers[0].reason == "cadence"
    assert submitted[-1].origin == "axe"


def test_due_refresh_with_no_eligible_providers_is_empty(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.eligible_usage_providers",
        lambda: (),
    )
    monkeypatch.setattr(
        "sase.procs.submit_proc_request",
        lambda request: pytest.fail("empty due refresh submitted a proc"),
    )
    receipt = request_due_usage_refresh(origin="axe")
    assert receipt.providers == ()
    assert receipt.operation_ids == ()


def test_inline_execution_runs_batch_in_process_without_proc(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.procs.submit_proc_request",
        lambda request: pytest.fail("inline refresh submitted a proc"),
    )
    seen: dict[str, object] = {}

    def fake_run(
        payload: dict[str, Any], *, now: float | None = None
    ) -> list[dict[str, Any]]:
        seen["payload"] = payload
        return [
            {
                "provider": "synth",
                "outcome": "ok",
                "reason_code": None,
                "skipped": None,
            }
        ]

    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh_runner.run_admitted_refresh", fake_run
    )
    receipt = submit_usage_refresh(
        ("synth",),
        explicit=True,
        origin="axe",
        execution="inline",
        plugin_specs={"synth": SYNTHETIC_PLUGIN_SPEC},
    )
    assert len(receipt.operation_ids) == 1
    operation_id = receipt.operation_ids[0]
    assert operation_id.startswith("usage-job:")
    assert receipt.providers[0].operation_id == operation_id
    assert receipt.inline_results == (
        {
            "provider": "synth",
            "outcome": "ok",
            "reason_code": None,
            "skipped": None,
        },
    )
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert [item["provider"] for item in payload["providers"]] == ["synth"]


def test_inline_execution_releases_leases_when_batch_raises(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.llm_provider.usage.refresh as refresh_mod

    released: list[str] = []
    real_release = refresh_mod.release_provider_usage_refresh
    monkeypatch.setattr(
        refresh_mod,
        "release_provider_usage_refresh",
        lambda *args, **kwargs: (
            released.append(args[0]) or real_release(*args, **kwargs)
        ),
    )
    attempts: list[tuple[str, str]] = []
    real_attempt = refresh_mod.record_provider_usage_refresh_attempt
    monkeypatch.setattr(
        refresh_mod,
        "record_provider_usage_refresh_attempt",
        lambda provider, *args, **kwargs: (
            attempts.append((provider, str(kwargs.get("reason_code"))))
            or real_attempt(provider, *args, **kwargs)
        ),
    )

    def boom(
        payload: dict[str, Any], *, now: float | None = None
    ) -> list[dict[str, Any]]:
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh_runner.run_admitted_refresh", boom
    )
    receipt = submit_usage_refresh(
        ("synth",),
        explicit=True,
        origin="axe",
        execution="inline",
        plugin_specs={"synth": SYNTHETIC_PLUGIN_SPEC},
    )
    assert receipt.inline_results == (
        {
            "provider": "synth",
            "outcome": "error",
            "reason_code": "probe_failed",
            "skipped": None,
        },
    )
    assert released == ["synth"]
    assert attempts == [("synth", "probe_failed")]


def test_receipt_carries_due_at_for_deferrals(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def due(*args: object, **kwargs: object) -> ProviderUsageRefreshDueOutcome:
        return ProviderUsageRefreshDueOutcome(
            version=1, due=False, reason="floor", due_at=1_800_000_300.0
        )

    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.evaluate_provider_usage_refresh_due",
        due,
    )
    receipt = submit_usage_refresh(
        ("synth",),
        explicit=False,
        origin="axe",
        plugin_specs={"synth": SYNTHETIC_PLUGIN_SPEC},
    )
    assert receipt.providers[0].status == "deferred"
    assert receipt.providers[0].due_at == 1_800_000_300.0
    assert receipt.providers[0].to_json()["due_at"] == 1_800_000_300.0


def test_wait_for_usage_refresh_operations_returns_when_released(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.llm_provider.usage.refresh as refresh_mod

    live = [
        _reservation("synth", "usage-job:abc123"),
    ]

    def fake_list(*, now: float | None = None) -> list[ProviderUsageRefreshReservation]:
        current = list(live)
        live.clear()
        return current

    monkeypatch.setattr(
        refresh_mod, "list_provider_usage_refresh_reservations", fake_list
    )
    refresh_mod.wait_for_usage_refresh_operations(
        ("usage-job:abc123",), 5.0, poll_interval=0.01
    )


def test_wait_for_usage_refresh_operations_times_out(
    usage_home: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.llm_provider.usage.refresh as refresh_mod

    monkeypatch.setattr(
        refresh_mod,
        "list_provider_usage_refresh_reservations",
        lambda *, now=None: (_reservation("synth", "usage-job:abc123"),),
    )
    with pytest.raises(TimeoutError, match="usage-job:abc123"):
        refresh_mod.wait_for_usage_refresh_operations(
            ("usage-job:abc123",), 0.05, poll_interval=0.01
        )

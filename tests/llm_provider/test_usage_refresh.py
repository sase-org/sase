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
    release_provider_usage_refresh,
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
    receipt = trigger_usage_refresh_after_limit_event(
        "synth", expires_at=1_800_000_100.0
    )
    assert receipt is not None
    assert submitted[0].origin == "limit_event"
    assert receipt.providers[0].provider == "synth"


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
    assert trigger_receipt is not None
    trigger_result = trigger_receipt.providers[0]
    assert trigger_result.status == "reserved"
    assert trigger_result.lease_id is not None
    assert submitted[-1].origin == "limit_event"

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
    release_provider_usage_refresh(
        "synth",
        trigger_result.context_id,
        trigger_result.account_generation,
        trigger_result.lease_id,
        now=reset_now + 1.0,
    )

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

    automatic_receipt = submit_usage_refresh(
        ("synth",),
        explicit=False,
        origin="axe",
        now=reset_now + 300.0,
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

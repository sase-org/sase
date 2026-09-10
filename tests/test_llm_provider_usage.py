"""Tests for the Rust-backed subscription-capacity usage facade."""

from __future__ import annotations

import pytest

from tests._rust_extension_module_helpers import install_fake_rust_extension


def test_usage_facade_rehydrates_store_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    calls: list[tuple[str, object]] = []

    def provider_usage_state_path(home: str) -> str:
        calls.append(("path", home))
        return str(tmp_path / "llm_provider_usage.json")

    def provider_usage_load(
        home: str,
        now: float,
        cadence_seconds: float,
        warn_percent: float,
        critical_percent: float,
    ) -> dict[str, object]:
        calls.append(
            (
                "load",
                (home, now, cadence_seconds, warn_percent, critical_percent),
            )
        )
        return {
            "version": 1,
            "snapshot": {
                "schema_version": 1,
                "generated_at": now,
                "collection_health": "empty",
                "providers": [],
                "attention": None,
            },
            "diagnostics": [{"provider": None, "message": "cache corrupt"}],
        }

    def provider_usage_record_observation(
        home: str,
        observation: dict[str, object],
        now: float,
    ) -> dict[str, object]:
        calls.append(("record", (home, observation, now)))
        return {
            "version": 1,
            "status": "recorded",
            "accepted": True,
            "provider": observation["provider"],
            "account_generation": observation["account_generation"],
            "reason": None,
        }

    def provider_usage_prepare_account_context(
        home: str,
        provider: str,
        context_id: str,
        now: float,
    ) -> dict[str, object]:
        calls.append(("context", (home, provider, context_id, now)))
        return {
            "version": 1,
            "provider": provider,
            "context_id": context_id,
            "account_generation": 2,
            "changed": True,
        }

    def provider_usage_reserve_refresh(
        home: str,
        request: dict[str, object],
        now: float,
    ) -> dict[str, object]:
        calls.append(("reserve", (home, request, now)))
        return {
            "version": 1,
            "status": "reserved",
            "reservation": {
                "version": 1,
                "provider": request["provider"],
                "context_id": request["context_id"],
                "account_generation": request["account_generation"],
                "operation_id": request["operation_id"],
                "lease_id": "lease-1",
                "reserved_at": now,
                "expires_at": now + 10.0,
            },
        }

    def provider_usage_release_refresh(
        home: str,
        provider: str,
        context_id: str,
        account_generation: int,
        lease_id: str,
        now: float,
    ) -> bool:
        calls.append(
            (
                "release",
                (home, provider, context_id, account_generation, lease_id, now),
            )
        )
        return True

    def provider_usage_indicator_schema_version() -> int:
        calls.append(("indicator_version", None))
        return 1

    def provider_usage_validate_indicator_config(
        indicator: object | None = None,
    ) -> dict[str, object]:
        calls.append(("indicator_validate", indicator))
        return {
            "schema_version": 1,
            "config": {
                "enabled": True,
                "default": {
                    "kind": "below_remaining_percent",
                    "below_remaining_percent": 20.0,
                },
                "weekly_all": {"kind": "always"},
                "providers": {},
            },
            "diagnostics": [],
        }

    def provider_usage_project_indicator(
        request: dict[str, object],
    ) -> dict[str, object]:
        calls.append(("indicator_project", request))
        return {
            "schema_version": 1,
            "generated_at": request["now"],
            "enabled": True,
            "diagnostics": [],
            "providers": [{"provider": "alpha"}],
            "entries": [
                {
                    "provider": "alpha",
                    "window_key": "weekly",
                }
            ],
        }

    install_fake_rust_extension(
        monkeypatch,
        provider_usage_state_path=provider_usage_state_path,
        provider_usage_load=provider_usage_load,
        provider_usage_record_observation=provider_usage_record_observation,
        provider_usage_prepare_account_context=provider_usage_prepare_account_context,
        provider_usage_reserve_refresh=provider_usage_reserve_refresh,
        provider_usage_release_refresh=provider_usage_release_refresh,
        provider_usage_indicator_schema_version=provider_usage_indicator_schema_version,
        provider_usage_validate_indicator_config=provider_usage_validate_indicator_config,
        provider_usage_project_indicator=provider_usage_project_indicator,
    )

    from sase.llm_provider import usage

    assert usage.provider_usage_state_path() == tmp_path / "llm_provider_usage.json"
    read = usage.load_provider_usage(now=123.0)
    assert read.version == 1
    assert read.snapshot["collection_health"] == "empty"
    assert read.diagnostics[0].message == "cache corrupt"

    write = usage.record_provider_usage_observation(
        {"provider": "alpha", "account_generation": 1},
        now=124.0,
    )
    assert write.status == usage.PROVIDER_USAGE_STORE_WRITE_RECORDED
    assert write.accepted is True

    context = usage.prepare_provider_usage_account_context(
        "alpha",
        "ctx-alpha",
        now=125.0,
    )
    assert context.account_generation == 2
    assert context.changed is True

    reserve = usage.reserve_provider_usage_refresh(
        "alpha",
        "ctx-alpha",
        2,
        "op-1",
        10.0,
        now=126.0,
    )
    assert reserve.status == usage.PROVIDER_USAGE_REFRESH_RESERVED
    assert reserve.reservation.lease_id == "lease-1"
    assert usage.release_provider_usage_refresh(
        "alpha",
        "ctx-alpha",
        2,
        "lease-1",
        now=127.0,
    )

    assert calls[1] == ("load", (str(tmp_path), 123.0, 300.0, 75.0, 90.0))
    assert calls[-2][0] == "reserve"
    assert calls[-1] == (
        "release",
        (str(tmp_path), "alpha", "ctx-alpha", 2, "lease-1", 127.0),
    )

    assert usage.provider_usage_indicator_schema_version() == 1
    validation = usage.provider_usage_validate_indicator_config({"default": "always"})
    assert validation.config["weekly_all"] == {"kind": "always"}
    projection = usage.provider_usage_project_indicator(
        read.snapshot,
        indicator={"default": "always"},
        eligible_providers={"alpha"},
        now=128.0,
    )
    assert projection.entries[0]["window_key"] == "weekly"
    assert calls[-3] == ("indicator_version", None)
    assert calls[-2] == ("indicator_validate", {"default": "always"})
    assert calls[-1][0] == "indicator_project"
    assert calls[-1][1]["eligible_providers"] == ["alpha"]


def test_usage_facade_rejects_invalid_envelopes() -> None:
    from sase.llm_provider.usage import (
        ProviderUsageStateError,
        ProviderUsageStoreRead,
    )

    with pytest.raises(ProviderUsageStateError, match="unsupported"):
        ProviderUsageStoreRead.from_wire(
            {"version": 2, "snapshot": {}, "diagnostics": []}
        )
    with pytest.raises(ProviderUsageStateError, match="diagnostics"):
        ProviderUsageStoreRead.from_wire(
            {"version": 1, "snapshot": {}, "diagnostics": "bad"}
        )


def test_usage_facade_requires_new_store_bindings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    install_fake_rust_extension(monkeypatch)

    from sase.llm_provider import usage

    with pytest.raises(AttributeError, match="provider_usage_load"):
        usage.load_provider_usage(now=123.0)
    with pytest.raises(AttributeError, match="provider_usage_project_indicator"):
        usage.provider_usage_project_indicator(
            {
                "schema_version": 1,
                "generated_at": 123.0,
                "collection_health": "empty",
                "providers": [],
                "attention": None,
            },
            now=123.0,
        )

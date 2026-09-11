from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._validate_sase_core_rs_tool_helpers import (
    load_validate_sase_core_rs,
    module_with_required_bindings,
)


pytestmark = pytest.mark.contract


def test_validate_sase_core_rs_requires_provider_disable_first_writer() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "provider_disable_wire_schema_version",
        "provider_disable_get",
        "provider_disable_set_relative",
        "provider_disable_set_until",
        "provider_disable_try_set_relative",
        "provider_disable_try_set_until",
        "provider_disable_clear",
    }
    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )

    def first_writer_module() -> SimpleNamespace:
        state: dict[str, dict[str, object]] = {}

        def try_relative(
            _home: str,
            provider: str,
            source: str,
            mode: str = "hard",
            duration_seconds: float = 0.0,
            now: float = 0.0,
        ) -> dict[str, object]:
            return _store_if_absent(
                state,
                provider,
                source,
                mode,
                now,
                now + duration_seconds,
            )

        def try_until(
            _home: str,
            provider: str,
            expires_at: float,
            source: str,
            mode: str = "hard",
            now: float = 0.0,
        ) -> dict[str, object]:
            return _store_if_absent(state, provider, source, mode, now, expires_at)

        def get_snapshot(_home: str, _current: float) -> dict[str, object]:
            return {
                "version": 2,
                "disables": [state[name] for name in sorted(state)],
            }

        return SimpleNamespace(
            provider_disable_try_set_relative=try_relative,
            provider_disable_try_set_until=try_until,
            provider_disable_get=get_snapshot,
        )

    def _store_if_absent(
        state: dict[str, dict[str, object]],
        provider: str,
        source: str,
        mode: str,
        current: float,
        expires_at: float,
    ) -> dict[str, object]:
        existing = state.get(provider)
        existing_expires = (
            existing.get("expires_at") if isinstance(existing, dict) else None
        )
        if (
            isinstance(existing, dict)
            and isinstance(existing_expires, (int, float))
            and current < float(existing_expires)
        ):
            return {"version": 2, "inserted": False, "record": existing}
        record = {
            "version": 2,
            "provider": provider,
            "created_at": current,
            "expires_at": expires_at,
            "source": source,
            "mode": mode,
        }
        state[provider] = record
        return {"version": 2, "inserted": True, "record": record}

    assert validator._validate_provider_disable_first_writer(first_writer_module())

    def always_insert(
        _home: str,
        provider: str,
        source: str,
        mode: str = "hard",
        duration_seconds: float = 0.0,
        now: float = 0.0,
    ) -> dict[str, object]:
        return {
            "version": 2,
            "inserted": True,
            "record": {
                "version": 2,
                "provider": provider,
                "created_at": now,
                "expires_at": now + duration_seconds,
                "source": source,
                "mode": mode,
            },
        }

    stale = first_writer_module()
    stale.provider_disable_try_set_relative = always_insert
    assert not validator._validate_provider_disable_first_writer(stale)


def test_validate_sase_core_rs_requires_provider_usage_store() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "provider_usage_observation_schema_version",
        "provider_usage_public_schema_version",
        "provider_usage_store_schema_version",
        "provider_usage_state_path",
        "provider_usage_load",
        "provider_usage_record_observation",
        "provider_usage_prepare_account_context",
        "provider_usage_reserve_refresh",
        "provider_usage_release_refresh",
        "provider_usage_refresh_due",
        "provider_usage_admit_refresh",
        "provider_usage_mark_refresh_due",
        "provider_usage_record_refresh_attempt",
        "provider_usage_validate_observation",
        "provider_usage_project_snapshot",
        "provider_usage_remaining_percent",
        "provider_usage_format_remaining_text",
        "provider_usage_classify_freshness",
        "provider_usage_window_applies",
        "provider_usage_summarize_for_model",
        "provider_usage_normalize_grok_billing",
    }
    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_provider_priority_routing() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "provider_priority_wire_schema_version",
        "provider_priority_get",
        "provider_priority_peek",
        "provider_priority_decode",
        "provider_priority_set_relative",
        "provider_priority_set_until",
        "provider_priority_clear",
        "provider_routing_context_wire_schema_version",
        "provider_routing_context_get",
        "provider_routing_context_from_parts",
        "provider_availability_wire_schema_version",
        "provider_availability_classify",
        "provider_availability_classify_many",
    }
    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )

    module = _provider_priority_module()
    assert validator._validate_provider_priority_routing_contract(module)

    stale = _provider_priority_module()
    stale.provider_availability_classify = lambda _context, facts: {
        "version": 1,
        "provider": facts["provider"],
        "availability": "preferred",
        "provenance": ["ordinary_available"],
        "actual_disable": None,
        "priority": None,
        "eligible_for_priority": True,
    }
    assert not validator._validate_provider_priority_routing_contract(stale)


def _provider_priority_module() -> SimpleNamespace:
    def from_parts(
        disables: list[dict[str, object]],
        priority: dict[str, object] | None,
        captured_at: float,
    ) -> dict[str, object]:
        active_priority = None
        if priority is not None:
            expires_at = priority.get("expires_at")
            if expires_at is None or captured_at < float(expires_at):
                active_priority = priority
        return {
            "version": 1,
            "captured_at": captured_at,
            "disables": disables,
            "priority": active_priority,
            "diagnostics": [],
        }

    def classify(
        context: dict[str, object],
        facts: dict[str, object],
    ) -> dict[str, object]:
        provider = str(facts["provider"])
        disables = context.get("disables")
        priority = context.get("priority")
        actual_disable = None
        if isinstance(disables, list):
            actual_disable = next(
                (
                    record
                    for record in disables
                    if isinstance(record, dict) and record.get("provider") == provider
                ),
                None,
            )
        is_priority = (
            isinstance(priority, dict) and priority.get("provider") == provider
        )
        if isinstance(actual_disable, dict) and actual_disable.get("mode") == "hard":
            availability = "unavailable"
            provenance = ["actual_hard_disable"]
            if is_priority:
                provenance.append("priority")
        elif isinstance(actual_disable, dict) and actual_disable.get("mode") == "soft":
            availability = "sparing"
            provenance = ["actual_soft_disable"]
            if is_priority:
                provenance.append("priority")
            elif priority is not None:
                provenance.append("priority_backup")
        elif is_priority:
            availability = "preferred"
            provenance = ["priority"]
        elif priority is not None:
            availability = "sparing"
            provenance = ["priority_backup"]
        else:
            availability = "preferred"
            provenance = ["ordinary_available"]
        return {
            "version": 1,
            "provider": provider,
            "availability": availability,
            "provenance": provenance,
            "actual_disable": actual_disable,
            "priority": priority,
            "eligible_for_priority": True,
        }

    return SimpleNamespace(
        provider_priority_wire_schema_version=lambda: 1,
        provider_routing_context_wire_schema_version=lambda: 1,
        provider_availability_wire_schema_version=lambda: 1,
        provider_routing_context_from_parts=from_parts,
        provider_availability_classify=classify,
        provider_availability_classify_many=lambda context, facts: [
            classify(context, item) for item in facts
        ],
    )

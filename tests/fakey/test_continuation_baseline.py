"""Fakey fixtures for continuation fallback shadow measurements."""

from __future__ import annotations

import json

from sase.continuation_baseline import (
    MEASUREMENT_LOG_NAME,
    measure_provider_preprocess,
    record_shadow_measurement,
)


def test_fakey_fallback_model_override_is_recorded_as_shadow_routing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_MODEL_OVERRIDE", "fakey-small")

    measurement = measure_provider_preprocess(
        "repair the failed command",
        capacity_tokens=4,
        model_tier="large",
        provider_name="fakey",
    )
    record_shadow_measurement(tmp_path, measurement)

    assert measurement.component == "provider_preprocess"
    assert measurement.fallback_routing.active is True
    assert measurement.fallback_routing.model == "fakey-small"
    assert measurement.fallback_routing.provider == "fakey"
    assert measurement.budget.threshold_exceeded is True
    [record] = [
        json.loads(line)
        for line in (tmp_path / MEASUREMENT_LOG_NAME).read_text().splitlines()
    ]
    assert record["fallback_routing"]["model"] == "fakey-small"

"""Thin Python wrappers around provider-usage core bindings."""

from __future__ import annotations

from sase.llm_provider.usage.store import (
    provider_usage_summarize_for_model,
    provider_usage_window_applies,
)
from tests._usage_view_helpers import usage_window


def test_summarize_for_model_uses_the_lowest_applicable_window() -> None:
    shared = usage_window(
        key="weekly",
        label="Week · all",
        used_percent=40.0,
        remaining_percent=60.0,
        vendor_state="allowed",
        applicability={"kind": "account"},
    )
    opus = usage_window(
        key="opus-week",
        label="Opus week",
        used_percent=94.0,
        remaining_percent=6.0,
        vendor_state="warning",
        applicability={"kind": "models", "model_ids": ["opus"]},
    )
    summary = provider_usage_summarize_for_model((shared, opus), "opus")
    other = provider_usage_summarize_for_model((shared, opus), "sonnet")

    assert summary is not None
    assert summary["remaining_percent"] == 6.0
    assert other is not None
    assert other["remaining_percent"] == 60.0


def test_window_applies_wrapper_rejects_unknown_fields() -> None:
    assert provider_usage_window_applies({"kind": "account"}) == "applies"

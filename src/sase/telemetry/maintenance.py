"""Thin configured-path adapter for explicit telemetry maintenance."""

from __future__ import annotations

from typing import Any

from sase.core.state_write_guard import assert_test_state_write_isolated
from sase.telemetry._config import get_telemetry_config

TEST_DATA_LABEL_MATCHES: dict[str, list[str]] = {
    "llm_provider": ["test-provider", "fakey"],
    "workflow": ["test-workflow"],
}


def cleanup_test_data(*, dry_run: bool) -> dict[str, Any]:
    """Preview or delete rows carrying the known exact test labels."""
    from sase_core_rs import (  # type: ignore[import-untyped]
        telemetry_cleanup_matching_labels,
    )

    config = get_telemetry_config()
    store_path = config.resolved_store_path
    if not dry_run:
        assert_test_state_write_isolated(
            store_path,
            category="telemetry-maintenance",
        )
    return telemetry_cleanup_matching_labels(
        str(store_path),
        {
            "label_matches": TEST_DATA_LABEL_MATCHES,
            "dry_run": dry_run,
        },
        config.busy_timeout_ms,
    )


__all__ = ["TEST_DATA_LABEL_MATCHES", "cleanup_test_data"]

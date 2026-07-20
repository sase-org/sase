"""Tests for update-status snapshot persistence and source merging."""

from __future__ import annotations

import json
from pathlib import Path

from sase.updates import (
    DEFAULT_UPDATE_STATUS_TTL_SECONDS,
    OutdatedComponent,
    ProviderUpdateCandidate,
    SCHEMA_VERSION,
    UpdateSourceStatus,
    UpdateStatus,
    merge_update_status,
    read_update_status_snapshot,
    update_status_snapshot_is_fresh,
    write_update_status_snapshot,
)


def test_update_status_snapshot_round_trip_and_freshness(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name="sase",
                install_type="editable",
                source_root="/src/sase",
                upstream_ref="origin/main",
            ),
        ),
        provider_candidates=(
            ProviderUpdateCandidate(
                provider="claude",
                display_name="Claude Code",
                installed_version="1.0.0",
                latest_version="1.1.0",
                manual_only=True,
            ),
        ),
        core_source=UpdateSourceStatus.success(90.0),
        plugin_source=UpdateSourceStatus(checked_at=80.0, error="registry down"),
        agent_cli_source=UpdateSourceStatus.success(100.0),
    )

    write_update_status_snapshot(status, path=path)

    assert read_update_status_snapshot(path=path) == status
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == 4
    assert envelope["provider_candidates"][0]["manual_only"] is True
    assert update_status_snapshot_is_fresh(status, now=110.0, ttl_seconds=20)
    assert not update_status_snapshot_is_fresh(status, now=130.0, ttl_seconds=20)


def test_previous_update_status_schema_is_treated_as_cache_miss(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION - 1,
                "checked_at": 100.0,
                "components": [
                    {
                        "display_name": "sase",
                        "role": "host",
                        "installed_version": "1.0.0",
                        "latest_version": "1.1.0",
                        "distribution_name": "sase",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert read_update_status_snapshot(path=path) is None


def test_update_status_snapshot_rejects_partially_invalid_rows(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(),
        core_source=UpdateSourceStatus.success(100.0),
        plugin_source=UpdateSourceStatus.success(100.0),
        agent_cli_source=UpdateSourceStatus.success(100.0),
    )
    write_update_status_snapshot(status, path=path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["components"] = [{"display_name": "partial"}]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_update_status_snapshot(path=path) is None


def test_merge_update_status_replaces_success_and_preserves_failed_sources() -> None:
    old_core = OutdatedComponent("sase", "host", "1", "2", "sase")
    old_plugin = OutdatedComponent("github", "plugin", "1", "2", "sase-github")
    old_provider = ProviderUpdateCandidate("claude", "Claude", "1", "2")
    previous = UpdateStatus(
        checked_at=100.0,
        components=(old_core, old_plugin),
        provider_candidates=(old_provider,),
        core_source=UpdateSourceStatus.success(100.0),
        plugin_source=UpdateSourceStatus.success(90.0),
        agent_cli_source=UpdateSourceStatus.success(80.0),
    )
    current_provider = ProviderUpdateCandidate("codex", "Codex", "3", "4")
    current = UpdateStatus(
        checked_at=200.0,
        components=(),
        provider_candidates=(current_provider,),
        core_source=UpdateSourceStatus.success(200.0),
        plugin_source=UpdateSourceStatus.failure("github unavailable"),
        agent_cli_source=UpdateSourceStatus.failure("npm unavailable"),
    )

    merged = merge_update_status(previous, current)

    assert merged.components == (old_plugin,)
    assert merged.provider_candidates == (old_provider,)
    assert merged.core_source == UpdateSourceStatus.success(200.0)
    assert merged.plugin_source == UpdateSourceStatus(
        checked_at=90.0,
        error="github unavailable",
    )
    assert merged.agent_cli_source == UpdateSourceStatus(
        checked_at=80.0,
        error="npm unavailable",
    )


def test_merge_update_status_successful_empty_is_not_unknown() -> None:
    previous = UpdateStatus(
        checked_at=100.0,
        components=(),
        provider_candidates=(ProviderUpdateCandidate("claude", "Claude", "1", "2"),),
        agent_cli_source=UpdateSourceStatus.success(100.0),
    )
    successful_empty = UpdateStatus(
        checked_at=200.0,
        components=(),
        agent_cli_source=UpdateSourceStatus.success(200.0),
    )

    merged = merge_update_status(previous, successful_empty)

    assert merged.provider_candidates == ()
    assert merged.agent_cli_source == UpdateSourceStatus.success(200.0)


def test_default_update_status_ttl_is_ten_minutes() -> None:
    assert DEFAULT_UPDATE_STATUS_TTL_SECONDS == 600


def test_update_status_snapshot_freshness_uses_default_ttl() -> None:
    status = UpdateStatus(checked_at=0.0, components=())
    future_status = UpdateStatus(checked_at=601.0, components=())

    assert update_status_snapshot_is_fresh(status, now=599.0)
    assert not update_status_snapshot_is_fresh(status, now=600.0)
    assert not update_status_snapshot_is_fresh(status, now=601.0)
    assert not update_status_snapshot_is_fresh(future_status, now=600.0)

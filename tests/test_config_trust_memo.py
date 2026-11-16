"""Trust-memo construction guards: O(N) merges and cheap cache hits.

Phase ``trust-memo`` requires construction-time config work to be O(projects),
not O(projects**2). These tests guard the three memos without asserting wall
time: per-primary registry-membership merges happen once per primary, a
cache-hit ``load_merged_config()`` neither loads YAML nor evaluates trust, and
edits, trust-store changes, and explicit clears invalidate correctly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from sase.config import _cache as config_cache
from sase.config import core as config_core
from sase.config.core import clear_config_cache, load_merged_config


def _write_user_config(global_dir: Path, content: dict) -> None:
    global_dir.mkdir(parents=True, exist_ok=True)
    (global_dir / "sase.yml").write_text(yaml.dump(content))


def _fake_primary_records(tmp_path: Path, count: int) -> list[SimpleNamespace]:
    records = []
    for index in range(count):
        primary = tmp_path / f"primary-{index}"
        primary.mkdir(parents=True, exist_ok=True)
        records.append(
            SimpleNamespace(
                is_project=True,
                system_managed=False,
                workspace_dir=str(primary),
                project_dir=str(tmp_path / f"proj-{index}"),
                project_name=f"proj-{index}",
                state="enabled",
                project_file=str(tmp_path / f"proj-{index}.sase"),
            )
        )
    for record in records:
        Path(record.project_file).write_text("state: enabled\n")
    return records


def test_project_identity_registry_scan_merges_once_per_primary(
    tmp_path: Path, monkeypatch
) -> None:
    """N evaluations over N primaries merge N times, not N**2."""
    from sase.config import _local_trust_membership as trust_membership

    count = 6
    records = _fake_primary_records(tmp_path, count)
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: list(records),
    )

    merge_calls = {"n": 0}
    real_merge = config_core.merge_config_sources

    def counting_merge(*args, **kwargs):
        merge_calls["n"] += 1
        return real_merge(*args, **kwargs)

    # Managed checkouts that match no primary force the full registry scan.
    managed_roots = []
    for index in range(count):
        managed = tmp_path / f"managed-{index}"
        managed.mkdir(parents=True, exist_ok=True)
        managed_roots.append(managed)

    with (
        patch("sase.config.core.merge_config_sources", side_effect=counting_merge),
        patch(
            "sase.config._local_trust_membership.resolve_project_config_read_path",
            side_effect=lambda primary: None,
        ),
    ):
        identities_first = [
            trust_membership._project_identity(
                root.resolve(), root / "sase" / "sase.yml"
            )
            for root in managed_roots
        ]
        merges_after_first_pass = merge_calls["n"]
        identities_second = [
            trust_membership._project_identity(
                root.resolve(), root / "sase" / "sase.yml"
            )
            for root in managed_roots
        ]

    assert identities_first == identities_second
    assert all(identity.startswith("checkout:v1:") for identity in identities_first)
    # First pass merges once per primary (plus at most one lower-layer merge);
    # the second pass over the same primaries must not merge again.
    assert merges_after_first_pass <= count + 1
    assert merge_calls["n"] == merges_after_first_pass


def test_load_merged_config_hit_skips_yaml_and_trust(
    tmp_path: Path, monkeypatch
) -> None:
    """A cache hit serves the merged config without YAML or trust work."""
    from sase.config import _sources as config_sources

    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "user"})
    local_path = tmp_path / "local.yml"
    local_path.write_text(yaml.dump({"key": "local"}))

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.get_local_config_path", return_value=local_path),
    ):
        first = load_merged_config()
        with (
            patch(
                "sase.config.core.local_config_snapshot",
                side_effect=AssertionError("snapshot must not run on cache hit"),
            ),
            patch(
                "sase.config._sources._load_yaml_file",
                side_effect=AssertionError("YAML must not load on cache hit"),
            ),
            patch(
                "sase.config.local_trust_enforcement.effective_local_layer",
                side_effect=AssertionError("trust must not evaluate on cache hit"),
            ),
        ):
            second = load_merged_config()

    assert second is first
    assert config_cache.merged_config_cache is not None
    assert config_cache.merged_config_cheap_key is not None


def test_load_merged_config_invalidates_on_edit_store_and_clear(
    tmp_path: Path,
) -> None:
    """Local edits, trust-store changes, and explicit clears all miss."""
    from sase.core.paths import sase_home

    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "user"})
    local_path = tmp_path / "local.yml"
    local_path.write_text(yaml.dump({"key": "v1"}))

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.get_local_config_path", return_value=local_path),
    ):
        first = load_merged_config()

        # Local edit with stat drift invalidates.
        local_path.write_text(yaml.dump({"key": "v2"}))
        import os

        new_ns = local_path.stat().st_mtime_ns + 10_000_000
        os.utime(local_path, ns=(new_ns, new_ns))
        second = load_merged_config()
        assert second is not first

        # Trust-store change invalidates the fast path: the next load must
        # re-read and re-evaluate even when the merged result is unchanged
        # (this local layer carries no commands, so the verdict stays put).
        from sase.config import _sources as config_sources

        store_path = sase_home() / "local_config_trust" / "records.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        before_cheap = config_cache.merged_config_cheap_key
        store_path.write_text("{}")
        after_cheap = config_sources._merged_config_cheap_key(
            config_core.current_config_token(),
            local_path,
        )
        assert after_cheap != before_cheap
        snapshot_calls = {"n": 0}
        real_snapshot = config_core.local_config_snapshot

        def counting_snapshot(*args, **kwargs):
            snapshot_calls["n"] += 1
            return real_snapshot(*args, **kwargs)

        with patch(
            "sase.config.core.local_config_snapshot", side_effect=counting_snapshot
        ):
            third = load_merged_config()
        assert snapshot_calls["n"] >= 1
        assert third == second

        # Explicit clear invalidates even when nothing changed.
        clear_config_cache()
        fourth = load_merged_config()
        assert fourth is not third
        assert fourth == third

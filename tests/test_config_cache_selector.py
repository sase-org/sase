"""Tests for machine-name overlay selection in the config caches.

The selected ``sase_<machine>.yml`` overlay is chosen by the machine-name
file, so that file's stat must feed the freshness token, and the parsed
overlay backing the agent-owner snapshot must be reused only while the token
holds. See ``test_config_cache.py`` for the merged-config cache itself.
"""

from pathlib import Path
from unittest.mock import patch

from sase.config import core as config_core
from sase.config.core import (
    current_config_token,
    get_agent_owner_config_snapshot,
    load_merged_config,
)
from sase.core.paths import machine_name_path
from tests._config_cache_helpers import (
    _wait_for_new_merged_config,
    _write_user_config,
)


def test_selector_stat_participates_in_config_freshness_token(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\nvalue: selected\n",
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        before = config_core._compute_current_config_token()
        machine_name_path().write_text("athena\n", encoding="utf-8")
        after = config_core._compute_current_config_token()

    assert before != after
    assert any(
        isinstance(part, tuple) and part and part[0] == str(machine_name_path())
        for part in after
    )


def test_selector_change_eventually_invalidates_merged_config(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\nvalue: first\n",
        encoding="utf-8",
    )
    (global_dir / "sase_zeus.yml").write_text(
        "id:\n  username: alice\n  machine_name: zeus\nvalue: second\n",
        encoding="utf-8",
    )
    selector = machine_name_path()
    selector.write_text("athena\n", encoding="utf-8")

    now = [10.0]
    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
    ):
        first = load_merged_config()
        assert first["value"] == "first"

        selector.write_text("zeus\n", encoding="utf-8")
        new_mtime_ns = selector.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(selector, ns=(new_mtime_ns, new_mtime_ns))
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01

        assert load_merged_config() is first
        second = _wait_for_new_merged_config(first)

    assert second["id"]["machine_name"] == "zeus"
    assert second["value"] == "second"


def test_owner_snapshot_reuses_parsed_overlay_until_token_changes(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    overlay = global_dir / "sase_athena.yml"
    overlay.write_text(
        "id:\n  username: alice\n  machine_name: athena\n", encoding="utf-8"
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")
    calls = {"count": 0}
    real_loader = config_core._load_yaml_file

    def counting_loader(path: Path) -> dict | None:
        calls["count"] += 1
        return real_loader(path)

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_yaml_file", side_effect=counting_loader),
    ):
        first = config_core.get_agent_owner_config_snapshot()
        second = config_core.get_agent_owner_config_snapshot()

    assert first is second
    assert first.owner is not None
    assert calls["count"] == 1


def test_rebound_config_dir_cold_reads_successor_paths(tmp_path: Path) -> None:
    """A leftover host-root populate cannot seed the successor's first reads."""
    host_dir = tmp_path / "host"
    successor_dir = tmp_path / "successor"
    _write_user_config(host_dir, {"marker": "host"})
    (host_dir / "sase_athena.yml").write_text(
        "id:\n  username: hostuser\n  machine_name: athena\n",
        encoding="utf-8",
    )
    _write_user_config(successor_dir, {"marker": "successor"})
    (successor_dir / "sase_athena.yml").write_text(
        "id:\n  username: successoruser\n  machine_name: athena\n",
        encoding="utf-8",
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", host_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        leftover_token = current_config_token()
        leftover_merged = load_merged_config()
        leftover_owner = get_agent_owner_config_snapshot()
    assert leftover_merged["marker"] == "host"
    assert leftover_owner.owner is not None
    assert leftover_owner.owner.username == "hostuser"

    with (
        patch("sase.config.core.CONFIG_DIR", successor_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        token = current_config_token()
        merged = load_merged_config()
        owner = get_agent_owner_config_snapshot()

    assert token is not leftover_token
    assert merged is not leftover_merged
    assert merged["marker"] == "successor"
    assert owner is not leftover_owner
    assert owner.owner is not None
    assert owner.owner.username == "successoruser"

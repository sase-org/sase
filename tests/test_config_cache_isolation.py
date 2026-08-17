"""Ordering regression for the config-cache refresh-worker leak (sase-ns.2).

A poisoner that leaves ``sase-config-token-refresh`` blocked used to publish
into the successor's cache generation after monkeypatch restored host
``CONFIG_DIR``. The autouse isolation fixture now drains that worker and
clears derived caches before host paths return. Running the poisoner then
the victim in one nested pytest subprocess pins the fixture lifecycle.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from sase.config import core as config_core
from sase.config.core import (
    CONFIG_TOKEN_REFRESH_THREAD_NAME,
    current_config_token,
    get_agent_owner_config_snapshot,
    load_merged_config,
)
from sase.core.paths import machine_name_path
from tests._config_cache_helpers import _reset_config_token_cache


pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]
_THIS_FILE = str(Path(__file__).resolve())


def _write_user_config(global_dir: Path, content: dict) -> None:
    global_dir.mkdir(exist_ok=True)
    (global_dir / "sase.yml").write_text(yaml.dump(content))


def test_poisoner_leaves_blocked_refresh_worker() -> None:
    """Start a refresh worker and leave it blocked for fixture teardown."""
    now = [10.0]
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute() -> tuple[str, int]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            refresh_started.set()
            release_refresh.wait(timeout=0.25)
        return ("poison", call_number)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        _reset_config_token_cache()
        assert current_config_token() == ("poison", 1)
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
        assert current_config_token() == ("poison", 1)
        assert refresh_started.wait(timeout=1.0)


def test_victim_first_reads_use_only_successor_patched_paths(tmp_path: Path) -> None:
    """Successor token, merged config, and owner come from the patched root."""
    assert not any(
        thread.name == CONFIG_TOKEN_REFRESH_THREAD_NAME and thread.is_alive()
        for thread in threading.enumerate()
    )

    successor_dir = tmp_path / "successor"
    _write_user_config(successor_dir, {"marker": "successor"})
    (successor_dir / "sase_athena.yml").write_text(
        "id:\n  username: successoruser\n  machine_name: athena\n",
        encoding="utf-8",
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", successor_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        token = current_config_token()
        merged = load_merged_config()
        owner = get_agent_owner_config_snapshot()

    assert token[0] == config_core._config_cache_generation
    assert merged["marker"] == "successor"
    assert owner.owner is not None
    assert owner.owner.username == "successoruser"
    assert not any(
        thread.name == CONFIG_TOKEN_REFRESH_THREAD_NAME and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_blocked_refresh_worker_does_not_poison_a_later_config_read(
    pytester: pytest.Pytester,
) -> None:
    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_ROOT),
        f"{_THIS_FILE}::test_poisoner_leaves_blocked_refresh_worker",
        f"{_THIS_FILE}::test_victim_first_reads_use_only_successor_patched_paths",
        timeout=60,
    )
    result.assert_outcomes(passed=2)


def test_no_live_refresh_worker_after_drain_window() -> None:
    """Fixture teardown must not leave a worker that can observe host paths."""
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        if not any(
            thread.name == CONFIG_TOKEN_REFRESH_THREAD_NAME and thread.is_alive()
            for thread in threading.enumerate()
        ):
            return
        time.sleep(0.01)  # sase-test-wait: poll interval for refresh-thread exit
    raise AssertionError("sase-config-token-refresh still alive after fixture drain")

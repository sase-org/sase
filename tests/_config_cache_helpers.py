"""Shared helpers for the config-cache test modules.

The merged-config and config-token caches publish new values from a
background refresh worker, so a test that edits config on disk polls with a
bounded deadline instead of asserting right after the write.
"""

import time
from pathlib import Path

import yaml
from sase.config.core import current_config_token, load_merged_config


def _write_user_config(global_dir: Path, content: dict) -> None:
    global_dir.mkdir(exist_ok=True)
    (global_dir / "sase.yml").write_text(yaml.dump(content))


def _wait_for_new_merged_config(previous: dict) -> dict:
    """Wait for a background token refresh to invalidate *previous*."""
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        current = load_merged_config()
        if current is not previous:
            return current
        time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
    raise AssertionError("config-token refresh did not publish before timeout")


def _wait_for_config_token(expected: tuple) -> None:
    """Wait for the background worker to publish *expected*."""
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        if current_config_token() == expected:
            return
        time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
    raise AssertionError(f"config token {expected!r} was not published before timeout")

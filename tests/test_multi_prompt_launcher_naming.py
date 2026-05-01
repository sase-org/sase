"""Tests for multi-prompt agent naming waits."""

import json
import os
import tempfile
import time

from sase.agent.multi_prompt_launcher import _wait_for_agent_naming


def test__wait_for_agent_naming_returns_name() -> None:
    """Returns name when agent_meta.json appears with a name field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_path = os.path.join(tmpdir, "agent_meta.json")
        with open(meta_path, "w") as f:
            json.dump({"pid": 123, "name": "alpha"}, f)

        result = _wait_for_agent_naming(tmpdir, timeout=2)
        assert result == "alpha"


def test__wait_for_agent_naming_returns_none_on_timeout() -> None:
    """Returns None when agent_meta.json never appears."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _wait_for_agent_naming(tmpdir, timeout=0.5)
        assert result is None


def test__wait_for_agent_naming_handles_missing_file() -> None:
    """Gracefully handles missing agent_meta.json (polls until timeout)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _wait_for_agent_naming(tmpdir, timeout=0.5)
        assert result is None


def test__wait_for_agent_naming_handles_corrupt_json() -> None:
    """Gracefully handles corrupt JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_path = os.path.join(tmpdir, "agent_meta.json")
        with open(meta_path, "w") as f:
            f.write("not valid json{{{")

        result = _wait_for_agent_naming(tmpdir, timeout=0.5)
        assert result is None


def test__wait_for_agent_naming_waits_for_name_field() -> None:
    """Polls until name field appears (not just the file)."""
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        meta_path = os.path.join(tmpdir, "agent_meta.json")
        # Write meta without name first.
        with open(meta_path, "w") as f:
            json.dump({"pid": 123}, f)

        def _write_name_later() -> None:
            time.sleep(0.3)
            with open(meta_path, "w") as f:
                json.dump({"pid": 123, "name": "beta"}, f)

        thread = threading.Thread(target=_write_name_later)
        thread.start()

        result = _wait_for_agent_naming(tmpdir, timeout=5)
        thread.join()
        assert result == "beta"

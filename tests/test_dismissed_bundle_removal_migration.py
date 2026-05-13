"""Tests for dismissed bundle legacy migration."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import load_dismissed_bundles
from tests._dismissed_agents_helpers import make_agent


def test_migration_from_monolithic_file(tmp_path: Path) -> None:
    """Test one-time migration from old monolithic bundles file."""
    bundles_dir = tmp_path / "bundles"
    old_file = tmp_path / "old_bundles.json"

    agent1 = make_agent(cl_name="cl_1", raw_suffix="20250615100000")
    agent2 = make_agent(cl_name="cl_2", raw_suffix="20250615110000")
    old_file.write_text(json.dumps([agent1.to_bundle_dict(), agent2.to_bundle_dict()]))

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", old_file),
    ):
        loaded = load_dismissed_bundles()
        assert len(loaded) == 2
        suffixes = {a.raw_suffix for a in loaded}
        assert suffixes == {"20250615100000", "20250615110000"}

        assert not old_file.exists()
        assert len(sorted(bundles_dir.glob("202506/*.json"))) == 2


def test_migration_skips_when_no_old_file(tmp_path: Path) -> None:
    """Test that migration is a no-op when the old file doesn't exist."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        loaded = load_dismissed_bundles()
        assert loaded == []

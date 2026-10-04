"""Last-used save destination persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.macro.save_state import load_last_used_locations, save_last_used_location


def test_last_used_locations_round_trip_independently(tmp_path: Path) -> None:
    state = tmp_path / "xprompt_save_state.json"
    with patch("sase.macro.save_state._SAVE_STATE_FILE", state):
        assert load_last_used_locations() == {}
        assert save_last_used_location("macro", "/tmp/xprompts")
        assert save_last_used_location("snippet", "/tmp/sase.yml")
        assert load_last_used_locations() == {
            "macro": "/tmp/xprompts",
            "snippet": "/tmp/sase.yml",
        }

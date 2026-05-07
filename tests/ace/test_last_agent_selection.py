"""Tests for persisted last agent selection loading."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.last_agent_selection import load_last_agent_selection


def test_load_last_agent_selection_rejects_unknown_item_type(tmp_path: Path) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    selection_file.write_text(
        json.dumps(
            {
                "display_name": "bad",
                "item_type": "unexpected",
                "project_name": "proj",
                "cl_name": None,
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file):
        assert load_last_agent_selection() is None


def test_load_last_agent_selection_rejects_non_string_fields(tmp_path: Path) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    selection_file.write_text(
        json.dumps(
            {
                "display_name": "bad",
                "item_type": "cl",
                "project_name": "proj",
                "cl_name": 42,
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file):
        assert load_last_agent_selection() is None

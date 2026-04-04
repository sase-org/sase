"""Tests for _emit_block in sase_commit_stop_hook."""

from __future__ import annotations

import json
from unittest.mock import patch

from sase.scripts.sase_commit_stop_hook import _emit_block


def test_codex_emit_block_includes_details_in_json(capsys: object) -> None:
    """Codex JSON reason must contain details when provided."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=True
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=False
        ),
    ):
        rc = _emit_block("generic reason", details="detailed instructions here")

    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[union-attr]
    payload = json.loads(captured.out.strip())
    assert payload["decision"] == "block"
    assert payload["reason"] == "detailed instructions here"
    assert "detailed instructions here" in captured.err


def test_codex_emit_block_falls_back_to_reason(capsys: object) -> None:
    """Codex JSON reason falls back to generic reason when details is None."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=True
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=False
        ),
    ):
        rc = _emit_block("generic reason")

    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[union-attr]
    payload = json.loads(captured.out.strip())
    assert payload["reason"] == "generic reason"
    assert captured.err == ""


def test_gemini_emit_block_includes_details_in_json(capsys: object) -> None:
    """Gemini JSON reason must contain details when provided."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=False
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=True
        ),
    ):
        rc = _emit_block("generic reason", details="detailed instructions here")

    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[union-attr]
    payload = json.loads(captured.out.strip())
    assert payload["decision"] == "deny"
    assert payload["reason"] == "detailed instructions here"


def test_claude_emit_block_returns_nonzero_with_details(capsys: object) -> None:
    """Claude gets details on stderr with non-zero exit."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=False
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=False
        ),
    ):
        rc = _emit_block("generic reason", details="detailed instructions here")

    assert rc == 2
    captured = capsys.readouterr()  # type: ignore[union-attr]
    assert captured.out == ""
    assert "detailed instructions here" in captured.err

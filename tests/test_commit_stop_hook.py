"""Tests for commit stop hook message and block behavior."""

from __future__ import annotations

import json
from unittest.mock import patch

from sase.scripts.sase_commit_stop_hook import (
    _build_commit_instruction_message,
    _emit_block,
)


def test_commit_instruction_non_pr_method_includes_scope_restriction() -> None:
    """Non-PR methods must constrain commit message scope to current commit."""
    message = _build_commit_instruction_message("/sase_git_commit", "create_commit")
    assert "The commit method type is `create_commit`." in message
    assert "describe only the changes in this commit" in message
    assert "Do NOT describe the entire pull request" in message


def test_commit_instruction_pr_method_omits_scope_restriction() -> None:
    """PR method should not include non-PR commit message scope constraints."""
    message = _build_commit_instruction_message(
        "/sase_git_commit", "create_pull_request"
    )
    assert "The commit method type is `create_pull_request`." in message
    assert "describe only the changes in this commit" not in message
    assert "Do NOT describe the entire pull request" not in message


def test_commit_instruction_unknown_method_defaults_to_scope_restriction() -> None:
    """Unknown methods should use non-PR scope guidance by default."""
    message = _build_commit_instruction_message("/sase_git_commit", "unexpected_method")
    assert "The commit method type is `unexpected_method`." in message
    assert "describe only the changes in this commit" in message
    assert "Do NOT describe the entire pull request" in message


def test_commit_instruction_includes_method_override_warning() -> None:
    """Instruction text must warn agents not to override the stated method."""
    message = _build_commit_instruction_message(
        "/sase_git_commit", "create_pull_request"
    )
    assert "Do NOT pass a --type value that conflicts" in message
    assert "--type create_pull_request" in message


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

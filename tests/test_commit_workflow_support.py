"""Tests for the run-owned commit ledger resolution helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from sase.workflows.commit.workflow_support import (
    is_conflict_state,
    resolve_head_commit_sha,
    resolve_head_tree_id,
)


def test_resolve_head_commit_sha_returns_resolved_revision() -> None:
    provider = MagicMock()
    provider.revision_id.return_value = "a" * 40

    assert resolve_head_commit_sha(provider, "/repo") == "a" * 40
    provider.revision_id.assert_called_once_with("HEAD", "/repo")


def test_resolve_head_tree_id_returns_resolved_tree() -> None:
    provider = MagicMock()
    provider.revision_id.return_value = "b" * 40

    assert resolve_head_tree_id(provider, "/repo") == "b" * 40
    provider.revision_id.assert_called_once_with("HEAD^{tree}", "/repo")


def test_resolve_head_commit_sha_is_best_effort_on_provider_error() -> None:
    provider = MagicMock()
    provider.revision_id.side_effect = RuntimeError("could not resolve revision")

    assert resolve_head_commit_sha(provider, "/repo") is None


def test_resolve_head_commit_sha_ignores_non_string_results() -> None:
    """A provider without ``revision_id`` support yields a MagicMock, not a str."""
    provider = MagicMock()

    assert resolve_head_commit_sha(provider, "/repo") is None


def test_resolve_head_commit_sha_ignores_blank_results() -> None:
    provider = MagicMock()
    provider.revision_id.return_value = "   "

    assert resolve_head_commit_sha(provider, "/repo") is None


def test_is_conflict_state_ignores_unconfigured_mock_methods() -> None:
    provider = MagicMock()

    assert is_conflict_state(provider, "/repo") is False


def test_is_conflict_state_detects_sync_in_progress() -> None:
    provider = MagicMock()
    provider.is_sync_in_progress.return_value = True

    assert is_conflict_state(provider, "/repo") is True


def test_is_conflict_state_detects_conflicted_files() -> None:
    provider = MagicMock()
    provider.is_sync_in_progress.return_value = False
    provider.get_conflicted_files.return_value = ["src/app.py"]

    assert is_conflict_state(provider, "/repo") is True

"""Source-code identity probes for runner-code refresh."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_runner_refresh import _source_code_identity
from sase.version._models import GitProbeResult, GitVersionMetadata


def _git_result(commit: str) -> GitProbeResult:
    return GitProbeResult(
        GitVersionMetadata(
            root="/repo",
            commit=commit,
            short_commit=commit[:9],
            tag=None,
            distance=None,
            dirty=False,
        )
    )


def test_source_code_identity_tracks_head_changes() -> None:
    checkout = Path("/repo")
    old = "a" * 40
    new = "b" * 40
    with patch(
        "sase.axe.run_agent_runner_refresh.probe_git_metadata_at_ref",
        side_effect=[_git_result(old), _git_result(old), _git_result(new)],
    ):
        assert _source_code_identity(checkout) == old
        assert _source_code_identity(checkout) == old
        assert _source_code_identity(checkout) == new


def test_source_code_identity_is_inert_without_git_metadata() -> None:
    with patch(
        "sase.axe.run_agent_runner_refresh.probe_git_metadata_at_ref",
        return_value=GitProbeResult(None, "not a git checkout"),
    ):
        assert _source_code_identity(Path("/wheel")) is None
    assert _source_code_identity(None) is None

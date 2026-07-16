"""Shared helpers for claimed revert-workspace tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.ace.revert_agent_workspace as raw
from tests.ace._revert_agent_helpers import _commit, _git, _init_repo, _msg


def _init_on_branch_cl(repo: Path, agent: str = "foo", subject: str = "feature") -> str:
    """Init a repo, branch ``cl``, and add one AGENT-tagged commit on it."""
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "cl")
    return _commit(repo, _msg(subject, agent), {f"{subject}.txt": f"{subject}\n"})


class _ClaimRecorder:
    """Records claim/release calls and hands out a fixed workspace number."""

    def __init__(self, workspace_num: int = 11) -> None:
        self.workspace_num = workspace_num
        self.claims: list[tuple[str, str, str | None]] = []
        self.releases: list[tuple[str, int, str | None, str | None]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_claim(
            project_file: str,
            workflow: str,
            pid: int,
            cl_name: str | None = None,
            **_: object,
        ) -> int:
            self.claims.append((project_file, workflow, cl_name))
            return self.workspace_num

        def fake_release(
            project_file: str,
            workspace_num: int,
            workflow: str | None = None,
            cl_name: str | None = None,
        ) -> object:
            self.releases.append((project_file, workspace_num, workflow, cl_name))
            return SimpleNamespace(success=True, error=None)

        monkeypatch.setattr(raw, "claim_next_axe_workspace", fake_claim)
        monkeypatch.setattr(raw, "release_workspace", fake_release)

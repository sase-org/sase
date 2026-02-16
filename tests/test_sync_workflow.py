"""Tests for the sync workflow YAML and its Python script steps."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.xprompt.workflow_loader import _load_workflow_from_file


# ---------------------------------------------------------------------------
# Workflow loading tests
# ---------------------------------------------------------------------------

SYNC_YML = Path(__file__).resolve().parent.parent / "xprompts" / "sync.yml"


@pytest.fixture()
def sync_workflow():
    """Load xprompts/sync.yml and return the Workflow object."""
    wf = _load_workflow_from_file(SYNC_YML)
    assert wf is not None, "Failed to load sync.yml"
    return wf


def test_sync_workflow_has_four_steps(sync_workflow) -> None:
    assert len(sync_workflow.steps) == 4


def test_sync_workflow_step_names(sync_workflow) -> None:
    names = [s.name for s in sync_workflow.steps]
    assert names == ["setup", "sync_attempt", "resolve", "report"]


def test_resolve_step_has_repeat_config(sync_workflow) -> None:
    resolve = sync_workflow.steps[2]
    assert resolve.repeat_config is not None
    assert resolve.repeat_config.max_iterations == 20


def test_resolve_step_has_if_condition(sync_workflow) -> None:
    resolve = sync_workflow.steps[2]
    assert resolve.condition is not None
    assert "sync_attempt.has_conflicts" in resolve.condition


def test_hidden_steps(sync_workflow) -> None:
    hidden_names = {s.name for s in sync_workflow.steps if s.hidden}
    assert hidden_names == {"setup", "sync_attempt", "report"}


def test_resolve_step_is_not_hidden(sync_workflow) -> None:
    resolve = sync_workflow.steps[2]
    assert not resolve.hidden


def test_workflow_has_branch_name_input(sync_workflow) -> None:
    input_names = [inp.name for inp in sync_workflow.inputs]
    assert "branch_name" in input_names


# ---------------------------------------------------------------------------
# sync_setup script tests
# ---------------------------------------------------------------------------


class TestSyncSetup:
    def _make_provider(self, branch_name: str = "my-branch"):
        provider = MagicMock()
        provider.get_branch_name.return_value = (True, branch_name)
        return provider

    @patch("sase.scripts.sync_setup.get_vcs_provider")
    @patch("sase.scripts.sync_setup.detect_vcs", return_value="git")
    def test_basic_git(self, mock_detect, mock_get_provider, capsys) -> None:
        mock_get_provider.return_value = self._make_provider("feature-x")
        from sase.scripts.sync_setup import main

        main(cwd="/fake/repo")

        out = capsys.readouterr().out
        assert "vcs_type=git" in out
        assert "branch_name=feature-x" in out
        assert "cwd=/fake/repo" in out
        assert "_chdir=/fake/repo" in out

    @patch("sase.scripts.sync_setup.get_vcs_provider")
    @patch("sase.scripts.sync_setup.detect_vcs", return_value="hg")
    def test_basic_hg(self, mock_detect, mock_get_provider, capsys) -> None:
        mock_get_provider.return_value = self._make_provider("default")
        from sase.scripts.sync_setup import main

        main(cwd="/fake/hg-repo")

        out = capsys.readouterr().out
        assert "vcs_type=hg" in out
        assert "branch_name=default" in out

    @patch("sase.scripts.sync_setup.detect_vcs", return_value=None)
    def test_no_vcs_detected(self, mock_detect, capsys) -> None:
        from sase.scripts.sync_setup import main

        main(cwd="/no/vcs")

        out = capsys.readouterr().out
        assert "vcs_type=unknown" in out
        assert "error=No VCS detected" in out

    @patch("sase.scripts.sync_setup.get_vcs_provider")
    @patch("sase.scripts.sync_setup.detect_vcs", return_value="git")
    def test_cwd_from_env(
        self, mock_detect, mock_get_provider, capsys, monkeypatch
    ) -> None:
        mock_get_provider.return_value = self._make_provider()
        monkeypatch.setenv("SASE_SYNC_CWD", "/env/repo")
        from sase.scripts.sync_setup import main

        main()

        out = capsys.readouterr().out
        assert "cwd=/env/repo" in out

    @patch("sase.scripts.sync_setup.get_vcs_provider")
    @patch("sase.scripts.sync_setup.detect_vcs", return_value="git")
    def test_cwd_param_takes_priority(
        self, mock_detect, mock_get_provider, capsys, monkeypatch
    ) -> None:
        mock_get_provider.return_value = self._make_provider()
        monkeypatch.setenv("SASE_SYNC_CWD", "/env/repo")
        from sase.scripts.sync_setup import main

        main(cwd="/param/repo")

        out = capsys.readouterr().out
        assert "cwd=/param/repo" in out

    @patch("sase.scripts.sync_setup.get_vcs_provider")
    @patch("sase.scripts.sync_setup.detect_vcs", return_value="git")
    def test_branch_name_failure(self, mock_detect, mock_get_provider, capsys) -> None:
        provider = MagicMock()
        provider.get_branch_name.return_value = (False, None)
        mock_get_provider.return_value = provider
        from sase.scripts.sync_setup import main

        main(cwd="/fake/repo")

        out = capsys.readouterr().out
        assert "branch_name=" in out


# ---------------------------------------------------------------------------
# sync_attempt script tests
# ---------------------------------------------------------------------------


class TestSyncAttempt:
    def _make_provider(
        self,
        *,
        sync_success: bool = True,
        sync_error: str | None = None,
        in_progress: bool = False,
        conflicted: list[str] | None = None,
    ):
        provider = MagicMock()
        provider.sync_workspace.return_value = (sync_success, sync_error)
        provider.is_sync_in_progress.return_value = in_progress
        provider.get_conflicted_files.return_value = conflicted or []
        return provider

    @patch("sase.scripts.sync_attempt.get_vcs_provider")
    def test_clean_sync(self, mock_get_provider, capsys) -> None:
        mock_get_provider.return_value = self._make_provider()
        from sase.scripts.sync_attempt import main

        main(cwd="/repo")

        out = capsys.readouterr().out
        assert "success=true" in out
        assert "has_conflicts=false" in out

    @patch("sase.scripts.sync_attempt.get_vcs_provider")
    def test_sync_with_conflicts(self, mock_get_provider, capsys) -> None:
        mock_get_provider.return_value = self._make_provider(
            sync_success=False,
            sync_error="rebase failed",
            in_progress=True,
            conflicted=["file1.py", "file2.py"],
        )
        from sase.scripts.sync_attempt import main

        main(cwd="/repo")

        out = capsys.readouterr().out
        assert "success=false" in out
        assert "has_conflicts=true" in out
        assert "file1.py" in out
        assert "file2.py" in out

    @patch("sase.scripts.sync_attempt.get_vcs_provider")
    def test_sync_failure_no_conflicts(self, mock_get_provider, capsys) -> None:
        mock_get_provider.return_value = self._make_provider(
            sync_success=False,
            sync_error="network error",
            in_progress=False,
        )
        from sase.scripts.sync_attempt import main

        main(cwd="/repo")

        out = capsys.readouterr().out
        assert "success=false" in out
        assert "has_conflicts=false" in out
        assert "error=network error" in out


# ---------------------------------------------------------------------------
# sync_report script tests
# ---------------------------------------------------------------------------


class TestSyncReport:
    def test_clean_sync(self, capsys) -> None:
        from sase.scripts.sync_report import main

        main(success=True, has_conflicts=False, all_resolved=False)

        out = capsys.readouterr().out
        assert "status=success" in out

    def test_conflicts_resolved(self, capsys) -> None:
        from sase.scripts.sync_report import main

        main(success=False, has_conflicts=True, all_resolved=True)

        out = capsys.readouterr().out
        assert "status=resolved" in out

    def test_conflicts_unresolved(self, capsys) -> None:
        from sase.scripts.sync_report import main

        main(success=False, has_conflicts=True, all_resolved=False)

        out = capsys.readouterr().out
        assert "status=unresolved" in out

    def test_non_conflict_error(self, capsys) -> None:
        from sase.scripts.sync_report import main

        main(success=False, has_conflicts=False, all_resolved=False)

        out = capsys.readouterr().out
        assert "status=error" in out

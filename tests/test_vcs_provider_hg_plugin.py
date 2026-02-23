"""Tests for the Hg pluggy plugin.

Verifies that :class:`HgPlugin` works correctly when routed through
:class:`VCSPluginManager`, producing identical results to :class:`_HgProvider`.
"""

from unittest.mock import MagicMock, patch

import pluggy
import pytest
from sase.vcs_provider._base import VCSProvider
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.hg import HgPlugin

_MOCK_TARGET = "sase.vcs_provider._command_runner.subprocess.run"


@pytest.fixture
def hg_provider() -> VCSPluginManager:
    """Create a VCSPluginManager backed by HgPlugin."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(HgPlugin())
    return VCSPluginManager(pm)


# === Tests for isinstance / type checks ===


def test_hg_plugin_provider_is_vcs_provider(hg_provider: VCSPluginManager) -> None:
    """The plugin-backed provider is a VCSProvider."""
    assert isinstance(hg_provider, VCSProvider)


def test_hg_plugin_is_command_runner() -> None:
    """HgPlugin inherits from CommandRunner."""
    from sase.vcs_provider._command_runner import CommandRunner

    plugin = HgPlugin()
    assert isinstance(plugin, CommandRunner)


# === Tests for core operations via plugin ===


@patch(_MOCK_TARGET)
def test_plugin_checkout_success(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.checkout("main", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_update", "main"]


@patch(_MOCK_TARGET)
def test_plugin_checkout_failure(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="branch not found"
    )
    success, error = hg_provider.checkout("bad", "/workspace")

    assert success is False
    assert isinstance(error, str)


@patch(_MOCK_TARGET)
def test_plugin_diff_success(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="diff output", stderr="")
    success, text = hg_provider.diff("/workspace")

    assert success is True
    assert text == "diff output"


@patch(_MOCK_TARGET)
def test_plugin_diff_clean(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, text = hg_provider.diff("/workspace")

    assert success is True
    assert text is None


@patch(_MOCK_TARGET)
def test_plugin_diff_revision(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="diff output", stderr="")
    success, text = hg_provider.diff_revision("abc123", "/workspace")

    assert success is True
    assert text == "diff output"
    assert mock_run.call_args[0][0] == ["hg", "diff", "-c", "abc123"]


@patch(_MOCK_TARGET)
def test_plugin_add_remove(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.add_remove("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["hg", "addremove"]


@patch(_MOCK_TARGET)
def test_plugin_commit(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is True
    assert error is None


@patch(_MOCK_TARGET)
def test_plugin_amend(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.amend("fix typo", "/workspace")

    assert success is True
    assert error is None


@patch(_MOCK_TARGET)
def test_plugin_amend_no_upload(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.amend("fix", "/workspace", no_upload=True)

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_amend", "--no-upload", "fix"]


@patch(_MOCK_TARGET)
def test_plugin_rebase(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.rebase("feature", "main", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_rebase", "feature", "main"]
    assert mock_run.call_args[1]["timeout"] == 600


@patch(_MOCK_TARGET)
def test_plugin_archive(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.archive("old-feature", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_archive", "old-feature"]


@patch(_MOCK_TARGET)
def test_plugin_prune(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.prune("dead-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_prune", "dead-branch"]


# === Tests for optional core operations ===


def test_plugin_get_default_parent_revision(
    hg_provider: VCSPluginManager,
) -> None:
    assert hg_provider.get_default_parent_revision("/workspace") == "p4head"


@patch(_MOCK_TARGET)
def test_plugin_is_sync_in_progress_true(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(
        returncode=0, stdout="U file.py\nR other.py\n", stderr=""
    )
    assert hg_provider.is_sync_in_progress("/workspace") is True


@patch(_MOCK_TARGET)
def test_plugin_is_sync_in_progress_false(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="R file.py\n", stderr="")
    assert hg_provider.is_sync_in_progress("/workspace") is False


@patch(_MOCK_TARGET)
def test_plugin_get_conflicted_files(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(
        returncode=0, stdout="U file.py\nR other.py\nU bar.py\n", stderr=""
    )
    files = hg_provider.get_conflicted_files("/workspace")
    assert files == ["file.py", "bar.py"]


# === Tests for VCS-agnostic operations ===


def test_plugin_prepare_description_for_reword(
    hg_provider: VCSPluginManager,
) -> None:
    result = hg_provider.prepare_description_for_reword("hello\nworld")
    assert isinstance(result, str)
    assert "\\n" in result
    assert "\n" not in result


def test_plugin_prepare_description_escapes_backslash(
    hg_provider: VCSPluginManager,
) -> None:
    result = hg_provider.prepare_description_for_reword("path\\to\\file")
    assert result == "path\\\\to\\\\file"


@patch(_MOCK_TARGET)
def test_plugin_get_change_url(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="12345\n", stderr="")
    success, url = hg_provider.get_change_url("/workspace")

    assert success is True
    assert url == "http://cl/12345"


@patch(_MOCK_TARGET)
def test_plugin_get_change_url_no_cl(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="not_a_number\n", stderr="")
    success, url = hg_provider.get_change_url("/workspace")

    assert success is True
    assert url is None


# === Tests for Google-internal operations ===


@patch(_MOCK_TARGET)
def test_plugin_reword(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.reword("new description", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["sase_hg_reword", "new description"]


@patch(_MOCK_TARGET)
def test_plugin_get_description(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(
        returncode=0, stdout="Full commit message\n", stderr=""
    )
    success, desc = hg_provider.get_description("abc123", "/workspace")

    assert success is True
    assert desc is not None
    assert "Full commit message" in desc


@patch(_MOCK_TARGET)
def test_plugin_get_description_short(
    mock_run: MagicMock, hg_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="Short subject\n", stderr="")
    success, desc = hg_provider.get_description("abc123", "/workspace", short=True)

    assert success is True
    assert desc is not None
    assert mock_run.call_args[0][0] == ["cl_desc", "-s"]


@patch(_MOCK_TARGET)
def test_plugin_mail(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.mail("abc123", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["hg", "mail", "-r", "abc123"]


@patch(_MOCK_TARGET)
def test_plugin_rewind(mock_run: MagicMock, hg_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = hg_provider.rewind(["/tmp/a.diff", "/tmp/b.diff"], "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == [
        "sase_hg_rewind",
        "/tmp/a.diff",
        "/tmp/b.diff",
    ]
    assert mock_run.call_args[1]["timeout"] == 600


# === Test registry integration ===


@patch("sase.vcs_provider._registry._resolve_vcs_name", return_value="hg")
def test_registry_routes_hg_through_plugin(mock_resolve: MagicMock) -> None:
    """get_vcs_provider returns a VCSPluginManager for hg."""
    from sase.vcs_provider._registry import get_vcs_provider

    provider = get_vcs_provider("/workspace")
    assert isinstance(provider, VCSPluginManager)
    assert isinstance(provider, VCSProvider)

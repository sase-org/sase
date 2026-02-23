"""Tests for the vcs_provider package."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pluggy
import pytest
from sase.vcs_provider import (
    VCSOperationError,
    VCSProvider,
    VCSProviderNotFoundError,
    get_vcs_provider,
)
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider._registry import _resolve_vcs_name, detect_vcs, detect_vcs_family
from sase.vcs_provider._types import CommandOutput
from sase.vcs_provider.config import get_vcs_provider_config, get_workspace_root
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

# === Tests for CommandOutput ===


def test_command_output_success() -> None:
    """Test CommandOutput reports success for returncode 0."""
    out = CommandOutput(0, "output", "")
    assert out.success is True


def test_command_output_failure() -> None:
    """Test CommandOutput reports failure for non-zero returncode."""
    out = CommandOutput(1, "", "error")
    assert out.success is False


# === Tests for errors ===


def test_vcs_operation_error() -> None:
    """Test VCSOperationError stores operation and message."""
    err = VCSOperationError("checkout", "branch not found")
    assert err.operation == "checkout"
    assert err.message == "branch not found"
    assert "checkout" in str(err)
    assert "branch not found" in str(err)


def test_vcs_provider_not_found_error() -> None:
    """Test VCSProviderNotFoundError stores directory."""
    err = VCSProviderNotFoundError("/some/dir")
    assert err.directory == "/some/dir"
    assert "/some/dir" in str(err)


# === Tests for registry / auto-detect ===


def test_get_vcs_provider_detects_hg() -> None:
    """Test get_vcs_provider detects .hg directory and returns a VCSProvider.

    When sase-hg plugin is installed, returns a VCSProvider.
    When not installed, raises VCSProviderNotFoundError.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".hg"))
        try:
            provider = get_vcs_provider(tmpdir)
            assert isinstance(provider, VCSProvider)
        except VCSProviderNotFoundError as exc:
            assert "Install the plugin" in str(exc)


def test_get_vcs_provider_not_found() -> None:
    """Test get_vcs_provider raises when no VCS detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(VCSProviderNotFoundError) as exc_info:
            get_vcs_provider(tmpdir)
        assert tmpdir in str(exc_info.value)


# === Tests for Google-internal method defaults ===


def test_vcs_provider_google_methods_raise() -> None:
    """Test that Google-internal methods raise NotImplementedError by default."""
    provider = _MinimalProvider()

    methods_to_test = [
        lambda: provider.sync_workspace("/cwd"),
        lambda: provider.reword("desc", "/cwd"),
        lambda: provider.reword_add_tag("tag", "val", "/cwd"),
        lambda: provider.get_description("rev", "/cwd"),
        lambda: provider.get_branch_name("/cwd"),
        lambda: provider.get_cl_number("/cwd"),
        lambda: provider.get_workspace_name("/cwd"),
        lambda: provider.has_local_changes("/cwd"),
        lambda: provider.get_bug_number("/cwd"),
        lambda: provider.mail("rev", "/cwd"),
        lambda: provider.fix("/cwd"),
        lambda: provider.upload("/cwd"),
        lambda: provider.find_reviewers("123", "/cwd"),
        lambda: provider.rewind(["/path"], "/cwd"),
        lambda: provider.get_change_url("/cwd"),
    ]

    for method in methods_to_test:
        with pytest.raises(NotImplementedError):
            method()


# === Tests for prepare_description_for_reword ===


def test_git_prepare_description_for_reword_passthrough() -> None:
    """Test that BareGitPlugin (via VCSPluginManager) returns description unchanged."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    manager = VCSPluginManager(pm)
    assert manager.prepare_description_for_reword("hello\nworld") == "hello\nworld"


def test_default_prepare_description_for_reword_passthrough() -> None:
    """Test that the base default returns description unchanged."""
    provider = _MinimalProvider()
    assert provider.prepare_description_for_reword("hello\nworld") == "hello\nworld"


class _MinimalProvider(VCSProvider):
    """Minimal concrete provider for testing defaults."""

    def checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def diff(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def apply_patches(
        self, patch_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]:
        return (True, None)

    def add_remove(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def clean_workspace(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def amend(
        self, note: str, cwd: str, *, no_upload: bool = False
    ) -> tuple[bool, str | None]:
        return (True, None)

    def rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]:
        return (True, None)

    def archive(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def prune(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    def stash_and_clean(
        self, diff_name: str, cwd: str, *, timeout: int = 300
    ) -> tuple[bool, str | None]:
        return (True, None)


# === Tests for _resolve_vcs_name ===


def test_resolve_vcs_name_env_var_override() -> None:
    """Env var SASE_VCS_PROVIDER=hg overrides auto-detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch.dict(os.environ, {"SASE_VCS_PROVIDER": "hg"}):
            assert _resolve_vcs_name(tmpdir) == "hg"


def test_resolve_vcs_name_env_var_auto() -> None:
    """SASE_VCS_PROVIDER=auto bypasses config and auto-detects."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch.dict(os.environ, {"SASE_VCS_PROVIDER": "auto"}):
            with patch(
                "sase.vcs_provider._registry.get_vcs_provider_config",
                return_value={"provider": "hg"},
            ):
                with patch(
                    "sase.vcs_provider._registry._classify_git_repo",
                    return_value="github",
                ):
                    assert _resolve_vcs_name(tmpdir) == "github"


def test_resolve_vcs_name_config_override() -> None:
    """Config provider: hg overrides auto-detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch.dict(os.environ, {}, clear=False):
            # Ensure env var is not set
            os.environ.pop("SASE_VCS_PROVIDER", None)
            with patch(
                "sase.vcs_provider._registry.get_vcs_provider_config",
                return_value={"provider": "hg"},
            ):
                assert _resolve_vcs_name(tmpdir) == "hg"


def test_resolve_vcs_name_config_auto() -> None:
    """Config provider: auto falls through to detect_vcs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SASE_VCS_PROVIDER", None)
            with patch(
                "sase.vcs_provider._registry.get_vcs_provider_config",
                return_value={"provider": "auto"},
            ):
                with patch(
                    "sase.vcs_provider._registry._classify_git_repo",
                    return_value="github",
                ):
                    assert _resolve_vcs_name(tmpdir) == "github"


def test_resolve_vcs_name_default_auto_detects() -> None:
    """No env/config falls through to detect_vcs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".hg"))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SASE_VCS_PROVIDER", None)
            with patch(
                "sase.vcs_provider._registry.get_vcs_provider_config",
                return_value={},
            ):
                assert _resolve_vcs_name(tmpdir) == "hg"


# === Tests for get_vcs_provider_config ===


def test_get_vcs_provider_config_missing_file() -> None:
    """Returns empty dict when config file doesn't exist."""
    with patch("sase.vcs_provider.config.load_merged_config", return_value={}):
        assert get_vcs_provider_config() == {}


def test_get_vcs_provider_config_no_section() -> None:
    """Returns empty dict when vcs_provider section is absent."""
    with patch(
        "sase.vcs_provider.config.load_merged_config",
        return_value={"llm_provider": {"provider": "gemini"}},
    ):
        assert get_vcs_provider_config() == {}


def test_get_vcs_provider_config_with_section() -> None:
    """Returns vcs_provider dict when section is present."""
    with patch(
        "sase.vcs_provider.config.load_merged_config",
        return_value={"vcs_provider": {"provider": "hg"}},
    ):
        result = get_vcs_provider_config()
        assert result == {"provider": "hg"}


# === Tests for get_workspace_root ===


def test_get_workspace_root_env_var() -> None:
    """Env var SASE_WORKSPACE_ROOT takes priority over config."""
    with patch.dict(os.environ, {"SASE_WORKSPACE_ROOT": "/tmp/ws"}):
        with patch(
            "sase.vcs_provider.config.get_vcs_provider_config",
            return_value={"workspace_root": "/other/path"},
        ):
            assert get_workspace_root() == "/tmp/ws"


def test_get_workspace_root_config() -> None:
    """Falls back to workspace_root from sase.yml config."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SASE_WORKSPACE_ROOT", None)
        with patch(
            "sase.vcs_provider.config.get_vcs_provider_config",
            return_value={"workspace_root": "/config/ws"},
        ):
            assert get_workspace_root() == "/config/ws"


def test_get_workspace_root_none() -> None:
    """Returns None when neither env var nor config is set."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SASE_WORKSPACE_ROOT", None)
        with patch(
            "sase.vcs_provider.config.get_vcs_provider_config",
            return_value={},
        ):
            assert get_workspace_root() is None


# === Tests for detect_vcs 3-value system ===


def test_detect_vcs_returns_hg() -> None:
    """detect_vcs returns 'hg' for Mercurial repos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".hg"))
        assert detect_vcs(tmpdir) == "hg"


def test_detect_vcs_returns_github() -> None:
    """detect_vcs returns 'github' for GitHub-hosted git repos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch(
            "sase.vcs_provider._registry._classify_git_repo",
            return_value="github",
        ):
            assert detect_vcs(tmpdir) == "github"


def test_detect_vcs_returns_bare_git() -> None:
    """detect_vcs returns 'bare_git' for bare-git repos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch(
            "sase.vcs_provider._registry._classify_git_repo",
            return_value="bare_git",
        ):
            assert detect_vcs(tmpdir) == "bare_git"


def test_detect_vcs_returns_none() -> None:
    """detect_vcs returns None when no VCS detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert detect_vcs(tmpdir) is None


# === Tests for detect_vcs_family ===


def test_detect_vcs_family_github_to_git() -> None:
    """detect_vcs_family collapses 'github' to 'git'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch(
            "sase.vcs_provider._registry._classify_git_repo",
            return_value="github",
        ):
            assert detect_vcs_family(tmpdir) == "git"


def test_detect_vcs_family_bare_git_to_git() -> None:
    """detect_vcs_family collapses 'bare_git' to 'git'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        with patch(
            "sase.vcs_provider._registry._classify_git_repo",
            return_value="bare_git",
        ):
            assert detect_vcs_family(tmpdir) == "git"


def test_detect_vcs_family_hg() -> None:
    """detect_vcs_family returns 'hg' unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".hg"))
        assert detect_vcs_family(tmpdir) == "hg"


def test_detect_vcs_family_none() -> None:
    """detect_vcs_family returns None when no VCS detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert detect_vcs_family(tmpdir) is None


# === Tests for _resolve_vcs_name with legacy 'git' override ===


def test_resolve_vcs_name_env_git_reclassifies() -> None:
    """SASE_VCS_PROVIDER=git re-classifies via _classify_git_repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"SASE_VCS_PROVIDER": "git"}):
            with patch(
                "sase.vcs_provider._registry._classify_git_repo",
                return_value="bare_git",
            ):
                assert _resolve_vcs_name(tmpdir) == "bare_git"


def test_resolve_vcs_name_config_git_reclassifies() -> None:
    """Config provider: git re-classifies via _classify_git_repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SASE_VCS_PROVIDER", None)
            with patch(
                "sase.vcs_provider._registry.get_vcs_provider_config",
                return_value={"provider": "git"},
            ):
                with patch(
                    "sase.vcs_provider._registry._classify_git_repo",
                    return_value="github",
                ):
                    assert _resolve_vcs_name(tmpdir) == "github"

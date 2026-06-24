"""Pytest configuration for sase tests."""

from collections.abc import Iterator
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
)
from sase.env_contracts import WORKSPACE_PIN_ENV_VARS


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--sase-update-visual-snapshots",
        action="store_true",
        default=False,
        help="Update ACE visual snapshot goldens instead of asserting them.",
    )
    parser.addoption(
        "--sase-visual-artifact-dir",
        default=".pytest_cache/sase-visual",
        help="Directory for ACE visual snapshot failure artifacts.",
    )


def redirect_sase_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> Path:
    """Redirect all ``~/.sase/...`` expansions to ``home``.

    Intended for tests that touch ``~/.sase/`` state and need
    writes/reads to land inside a tmp_path without each call site
    threading module-level constants.  Patches both :meth:`Path.expanduser`
    and :func:`os.path.expanduser` because different call sites in the
    codebase use different APIs (``Path.expanduser`` only expands the
    leading ``~`` segment, so patching it at the Path level is required
    to redirect multi-segment ``~/.sase/...`` paths).

    Returns ``home`` for convenience.
    """
    home.mkdir(parents=True, exist_ok=True)
    original_path_expanduser = Path.expanduser
    original_os_expanduser = os.path.expanduser
    ambient_home_env = os.environ.get("HOME")

    if home.name == ".sase":
        monkeypatch.setenv("HOME", str(home.parent))
        monkeypatch.setenv("SASE_HOME", "~/.sase")
    else:
        monkeypatch.setenv("SASE_HOME", str(home))
    redirect_home_env = (
        os.environ.get("HOME") if home.name == ".sase" else ambient_home_env
    )

    def _current_sase_home() -> Path:
        if home.name == ".sase":
            return Path.home() / ".sase"
        return home

    def _home_env_overridden() -> bool:
        """True if a test has set HOME to a different value than at setup time."""
        return os.environ.get("HOME") != redirect_home_env

    def _fake_os(path):  # accepts str or os.PathLike
        s = os.fspath(path) if hasattr(path, "__fspath__") else path
        if (
            isinstance(s, str)
            and (s.startswith("~/.sase/") or s == "~/.sase")
            and not _home_env_overridden()
        ):
            current_home = _current_sase_home()
            if s.startswith("~/.sase/"):
                return str(current_home / s[len("~/.sase/") :])
            return str(current_home)
        return original_os_expanduser(path)

    def _fake_path(self: Path) -> Path:
        # Defer when either a test has further patched os.path.expanduser
        # or a test has redirected HOME itself.
        if os.path.expanduser is not _fake_os or _home_env_overridden():
            return original_path_expanduser(self)
        s = str(self)
        if s.startswith("~/.sase/"):
            return _current_sase_home() / s[len("~/.sase/") :]
        if s == "~/.sase":
            return _current_sase_home()
        return original_path_expanduser(self)

    monkeypatch.setattr(os.path, "expanduser", _fake_os)
    monkeypatch.setattr(Path, "expanduser", _fake_path)
    return home


@pytest.fixture(autouse=True)
def _isolate_sase_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Redirect ``~/.sase/`` to a per-test tmpdir so tests never touch real state.

    Uses ``tmp_path_factory`` (not ``tmp_path``) so the fake sase home lives
    in a sibling directory and doesn't pollute tests that iterate over their
    own ``tmp_path``.
    """
    fake_home = tmp_path_factory.mktemp("home")
    redirect_sase_home(monkeypatch, fake_home / ".sase")


@pytest.fixture(autouse=True)
def _clear_agent_env_vars(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear ambient SASE agent env vars before each test.

    Prevents launcher state from leaking into tests and causing side effects
    like bogus COMMITS entries in real ChangeSpec files or extra linked-repo
    dirty checks from the live agent workspace.  Both the canonical
    ``SASE_LINKED_REPO*`` vars and the deprecated ``SASE_SIBLING_REPO*`` aliases
    are scrubbed so finalizer tests don't inherit the developer's real linked
    repositories (e.g. a dirty chezmoi checkout) from the surrounding agent.
    """
    keys_to_clear = {
        key
        for key in os.environ
        if (
            key.startswith("SASE_AGENT_")
            or key.startswith("SASE_LINKED_REPO_")
            or key.startswith("SASE_SIBLING_REPO_")
            or key
            in {
                "SASE_ARTIFACTS_DIR",
                "SASE_BEAD_ID",
                "SASE_LINKED_REPOS_JSON",
                "SASE_SIBLING_REPOS_JSON",
            }
        )
    }
    keys_to_clear.update(WORKSPACE_PIN_ENV_VARS)

    for key in keys_to_clear:
        monkeypatch.delenv(key, raising=False)

    yield

    for key in WORKSPACE_PIN_ENV_VARS:
        os.environ.pop(key, None)


@pytest.fixture(scope="session")
def _test_llm_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a harmless CLI stub for default-provider autodetection tests."""
    bin_dir = tmp_path_factory.mktemp("llm-bin")
    claude = bin_dir / "claude"
    claude.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        "  printf 'Claude Code test stub\\n'\n"
        "  exit 0\n"
        "fi\n"
        "printf 'Claude Code test stub\\n' >&2\n"
        "exit 0\n",
        encoding="utf-8",
    )
    claude.chmod(0o755)
    return bin_dir


@pytest.fixture(autouse=True)
def _default_test_llm_cli(monkeypatch: pytest.MonkeyPatch, _test_llm_bin: Path) -> None:
    """Keep tests deterministic on CI hosts without provider CLIs installed."""
    path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{_test_llm_bin}{os.pathsep}{path}")


@pytest.fixture(autouse=True)
def _isolate_default_llm_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent ambient user config from forcing a default effort in tests."""
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: None)


@pytest.fixture(autouse=True)
def _mock_system_clipboard(request: pytest.FixtureRequest):
    """Prevent tests from touching the real system clipboard / X11 display."""
    if request.node.get_closest_marker("real_clipboard"):
        yield
        return

    with patch("sase.core.clipboard._clipboard_commands", return_value=[]):
        yield


@pytest.fixture(autouse=True)
def _clear_config_caches() -> None:
    """Drop the merged-config / mentor-profile caches before each test.

    The runtime caches live at module scope and would otherwise carry parsed
    config across tests that patch ``load_merged_config`` or rewrite tmp_path
    sase.yml files between runs.
    """
    from sase.config import core as config_core
    from sase.config import mentor as mentor_config

    config_core._default_config_cache = None
    config_core._plugin_configs_cache = None
    config_core._merged_config_cache_token = None
    config_core._merged_config_cache_value = None

    mentor_config._mentor_profiles_cache_token = None
    mentor_config._mentor_profiles_cache_value = None
    mentor_config._local_profile_names_cache_token = None
    mentor_config._local_profile_names_cache_value = None


@pytest.fixture
def make_changespec() -> "type[_ChangeSpecFactory]":  # Return a callable factory class
    """Fixture that provides a factory for creating ChangeSpec objects for testing."""
    return _ChangeSpecFactory


class _ChangeSpecFactory:
    """Factory class for creating ChangeSpec objects in tests."""

    @staticmethod
    def create(
        name: str = "test",
        description: str = "desc",
        status: str = "Ready",
        cl: str | None = None,
        parent: str | None = None,
        file_path: str = "/home/user/.sase/projects/myproject/myproject.sase",
        commits: list[CommitEntry] | None = None,
        hooks: list[HookEntry] | None = None,
        comments: list[CommentEntry] | None = None,
    ) -> ChangeSpec:
        """Create a ChangeSpec for testing."""
        return ChangeSpec(
            name=name,
            description=description,
            parent=parent,
            cl=cl,
            status=status,
            file_path=file_path,
            line_number=1,
            commits=commits,
            hooks=hooks,
            comments=comments,
        )

    @staticmethod
    def create_with_file(
        name: str = "test_feature",
        cl: str | None = "http://cl/123456789",
        status: str = "Mailed",
        parent: str | None = None,
    ) -> ChangeSpec:
        """Create a ChangeSpec backed by a temporary project spec file on disk.

        The caller is responsible for cleaning up the temp file via
        ``Path(cs.file_path).unlink()``.
        """
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".sase") as f:
            parent_val = parent if parent else "None"
            cl_val = cl if cl else "None"
            f.write(f"""# Test Project

## ChangeSpec

NAME: {name}
DESCRIPTION:
  A test feature
PARENT: {parent_val}
CL: {cl_val}
STATUS: {status}

---
""")
            return ChangeSpec(
                name=name,
                description="A test feature",
                parent=parent,
                cl=cl,
                status=status,
                file_path=f.name,
                line_number=6,
            )

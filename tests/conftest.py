"""Pytest configuration for sase tests."""

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
    initial_home_env = os.environ.get("HOME")

    def _home_env_overridden() -> bool:
        """True if a test has set HOME to a different value than at setup time."""
        return os.environ.get("HOME") != initial_home_env

    def _fake_os(path):  # accepts str or os.PathLike
        s = os.fspath(path) if hasattr(path, "__fspath__") else path
        if (
            isinstance(s, str)
            and (s.startswith("~/.sase/") or s == "~/.sase")
            and not _home_env_overridden()
        ):
            if s.startswith("~/.sase/"):
                return str(home / s[len("~/.sase/") :])
            return str(home)
        return original_os_expanduser(path)

    def _fake_path(self: Path) -> Path:
        # Defer when either a test has further patched os.path.expanduser
        # or a test has redirected HOME itself.
        if os.path.expanduser is not _fake_os or _home_env_overridden():
            return original_path_expanduser(self)
        s = str(self)
        if s.startswith("~/.sase/"):
            return home / s[len("~/.sase/") :]
        if s == "~/.sase":
            return home
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
    redirect_sase_home(monkeypatch, tmp_path_factory.mktemp("sase_home"))


@pytest.fixture(autouse=True)
def _clear_agent_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all SASE_AGENT_* env vars (plus SASE_ARTIFACTS_DIR) before each test.

    Prevents agent env vars set by the launcher from leaking into tests and
    causing side effects like bogus COMMITS entries in real ChangeSpec files.
    """
    for key in list(os.environ):
        if key.startswith("SASE_AGENT_") or key == "SASE_ARTIFACTS_DIR":
            monkeypatch.delenv(key)


@pytest.fixture(autouse=True)
def _mock_system_clipboard():
    """Prevent tests from touching the real system clipboard."""
    with patch("sase.ace.tui.widgets._vim_normal_ops.copy_to_system_clipboard"):
        yield


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
        file_path: str = "/home/user/.sase/projects/myproject/myproject.gp",
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
            test_targets=None,
            kickstart=None,
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
        """Create a ChangeSpec backed by a temporary .gp file on disk.

        The caller is responsible for cleaning up the temp file via
        ``Path(cs.file_path).unlink()``.
        """
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".gp") as f:
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
                test_targets=None,
                kickstart=None,
                file_path=f.name,
                line_number=6,
            )

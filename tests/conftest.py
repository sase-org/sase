"""Pytest configuration for sase tests."""

import os
import tempfile
from unittest.mock import patch

import pytest
from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
)


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
def _reset_agent_cache():
    """Reset the agent loader cache before each test to prevent cross-test leakage."""
    from sase.ace.tui.models.agent_loader import _cache

    _cache._agents = None
    _cache._tracker = None


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

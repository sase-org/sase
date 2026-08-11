"""Shared domain fixtures and factories for the test suite."""

import tempfile
from pathlib import Path

import pytest
from sase.ace.patch import (
    Patch,
    CommentEntry,
    CommitEntry,
    HookEntry,
)
from tests._project_display_case import ProjectDisplayCase


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect notification gate persistence to a temporary directory."""
    from sase.notification_gates import paths
    from sase.notifications import pending_actions, store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


@pytest.fixture
def project_display_case() -> ProjectDisplayCase:
    """Return the shared canonical-key/display-label mismatch case."""
    return ProjectDisplayCase()


@pytest.fixture
def make_patch(tmp_path: Path) -> "_PatchFactory":
    """Fixture that provides a factory for creating Patch objects for testing."""
    return _PatchFactory(tmp_path)


@pytest.fixture
def make_changespec(make_patch: "_PatchFactory") -> "_PatchFactory":
    """Legacy compatibility fixture alias for older tests."""
    return make_patch


class _PatchFactory:
    """Factory class for creating Patch objects in tests."""

    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path

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
        pr_origin: str | None = None,
    ) -> Patch:
        """Create a Patch for testing."""
        return Patch(
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
            pr_origin=pr_origin,
        )

    def create_with_file(
        self,
        name: str = "test_feature",
        cl: str | None = "http://cl/123456789",
        status: str = "Mailed",
        parent: str | None = None,
    ) -> Patch:
        """Create a Patch backed by a temporary project spec file on disk.

        The caller is responsible for cleaning up the temp file via
        ``Path(cs.file_path).unlink()``.
        """
        with tempfile.NamedTemporaryFile(
            dir=self._tmp_path,
            mode="w",
            delete=False,
            suffix=".sase",
        ) as f:
            parent_val = parent if parent else "None"
            cl_val = cl if cl else "None"
            f.write(f"""# Test Project

## ChangeSpec

NAME: {name}
DESCRIPTION:
  A test feature
PARENT: {parent_val}
PR: {cl_val}
STATUS: {status}

---
""")
            return Patch(
                name=name,
                description="A test feature",
                parent=parent,
                cl=cl,
                status=status,
                file_path=f.name,
                line_number=6,
            )

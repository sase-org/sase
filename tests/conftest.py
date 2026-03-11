"""Pytest configuration for sase tests."""

import tempfile
from pathlib import Path

import pytest
from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
)
from sase.spec_writer.handlers import dispatch
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse


def _dispatch_directly(
    request: SpecWriteRequest, timeout: float = 10.0
) -> SpecWriteResponse:
    """Bypass the file-based queue and dispatch directly to handlers."""
    return dispatch(request)


_SPEC_WRITER_CALLER_MODULES = [
    # Source module (handles inline imports in ace.revert, ace.comments,
    # ace.hooks, ace.mentors)
    "sase.spec_writer.client",
    # Modules with top-level imports (cached references need patching)
    "sase.accept_workflow.renumber",
    "sase.ace.operations",
    "sase.ace.revert",
    "sase.commit_utils.entries",
    "sase.commit_utils.modifiers",
    "sase.commit_workflow.changespec_operations",
    "sase.commit_workflow.project_file_utils",
    "sase.rewind_workflow.renumber",
    "sase.running_field",
    "sase.workspace_provider.plugins.bare_git_ref",
    "sase.workspace_utils",
    "sase.status_state_machine.transitions",
]


@pytest.fixture(autouse=True)
def _bypass_spec_writer_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch submit_spec_write_and_wait to dispatch directly, bypassing the queue."""
    for mod in _SPEC_WRITER_CALLER_MODULES:
        monkeypatch.setattr(
            f"{mod}.submit_spec_write_and_wait",
            _dispatch_directly,
        )


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

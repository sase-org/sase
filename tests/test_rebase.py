"""Tests for the rebase feature (PARENT field updates and eligible parents)."""

import tempfile
from pathlib import Path

import pytest

from sase.ace.tui.actions.proposal_rebase import (
    _ROOT_PARENT_SENTINEL,
    _format_parent_for_timestamp,
    _rebase_task,
)
from sase.status_state_machine import update_changespec_parent_atomic
from sase.status_state_machine.field_updates import _apply_parent_update


def _create_test_project_file_with_parent(
    status: str = "Ready", parent: str | None = None
) -> str:
    """Create a temporary project file with a test ChangeSpec."""
    parent_line = f"PARENT: {parent}\n" if parent else ""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".gp") as f:
        f.write(f"""# Test Project

## ChangeSpec

NAME: Test Feature
DESCRIPTION:
  A test feature for unit testing
{parent_line}CL: None
STATUS: {status}
TEST TARGETS: None

---
""")
        return f.name


def _create_multi_changespec_file() -> str:
    """Create a project file with multiple ChangeSpecs for testing eligible parents."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".gp") as f:
        f.write("""# Test Project

NAME: Feature A
DESCRIPTION:
  First feature
CL: http://cl/123
STATUS: Draft

---

NAME: Feature B
DESCRIPTION:
  Second feature
PARENT: Feature A
CL: http://cl/456
STATUS: Ready

---

NAME: Feature C
DESCRIPTION:
  Third feature
CL: http://cl/789
STATUS: Mailed

---

NAME: Feature D
DESCRIPTION:
  Fourth feature (terminal)
CL: http://cl/999
STATUS: Submitted

---

NAME: Feature E
DESCRIPTION:
  Fifth feature (terminal)
CL: None
STATUS: Reverted

---
""")
        return f.name


# === Tests for _apply_parent_update ===


def test_apply_parent_update_existing_field() -> None:
    """Test updating an existing PARENT field."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  A test feature\n",
        "PARENT: OldParent\n",
        "CL: http://cl/123\n",
        "STATUS: Ready\n",
    ]

    result = _apply_parent_update(lines, "Test Feature", "NewParent")
    assert "PARENT: NewParent\n" in result
    assert "PARENT: OldParent" not in result


# === Tests for update_changespec_parent_atomic ===


def test_update_changespec_parent_atomic_add_parent() -> None:
    """Test adding PARENT when it doesn't exist."""
    project_file = _create_test_project_file_with_parent(status="Ready", parent=None)

    try:
        update_changespec_parent_atomic(project_file, "Test Feature", "NewParent")

        with open(project_file, encoding="utf-8") as f:
            content = f.read()
            assert "PARENT: NewParent" in content

    finally:
        Path(project_file).unlink()


def test_update_changespec_parent_atomic_remove_parent() -> None:
    """Test removing PARENT field."""
    project_file = _create_test_project_file_with_parent(
        status="Ready", parent="OldParent"
    )

    try:
        update_changespec_parent_atomic(project_file, "Test Feature", None)

        with open(project_file, encoding="utf-8") as f:
            content = f.read()
            assert "PARENT:" not in content

    finally:
        Path(project_file).unlink()


def test_format_parent_for_timestamp_root_values() -> None:
    assert _format_parent_for_timestamp(None) == "root"
    assert _format_parent_for_timestamp(_ROOT_PARENT_SENTINEL) == "root"
    assert _format_parent_for_timestamp("Parent A") == "Parent A"


def test_rebase_task_records_parent_and_rebase_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful rebase updates PARENT and records the parent transition."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text(
        """\
NAME: Test Feature
DESCRIPTION:
  A test feature for unit testing
PARENT: Old Parent
CL: None
STATUS: Ready


""",
        encoding="utf-8",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    released: list[tuple[str, int, str, str]] = []

    class FakeProvider:
        def __init__(self) -> None:
            self.rebased_to: str | None = None

        def resolve_revision(
            self, changespec_name: str, project_basename: str, workspace: str
        ) -> str:
            assert changespec_name == "Test Feature"
            assert project_basename == "proj"
            assert workspace == str(workspace_dir)
            return "resolved-revision"

        def checkout(self, revision: str, workspace: str) -> tuple[bool, str]:
            assert revision == "resolved-revision"
            assert workspace == str(workspace_dir)
            return (True, "")

        def get_default_parent_revision(self, workspace: str) -> str:
            assert workspace == str(workspace_dir)
            return "default-parent-revision"

        def rebase(
            self, changespec_name: str, rebase_parent: str, workspace: str
        ) -> tuple[bool, str]:
            assert changespec_name == "Test Feature"
            assert workspace == str(workspace_dir)
            self.rebased_to = rebase_parent
            return (True, "")

    provider = FakeProvider()

    monkeypatch.setattr(
        "sase.workflows.commit_utils.run_sase_hg_clean",
        lambda workspace, workflow: (True, ""),
    )
    monkeypatch.setattr(
        "sase.running_field.get_first_available_axe_workspace",
        lambda project: 7,
    )
    monkeypatch.setattr(
        "sase.running_field.get_workspace_directory_for_num",
        lambda workspace_num, project_basename: (str(workspace_dir), None),
    )
    monkeypatch.setattr(
        "sase.running_field.claim_workspace",
        lambda project, workspace_num, workflow, pid, changespec: True,
    )
    monkeypatch.setattr(
        "sase.running_field.release_workspace",
        lambda project, workspace_num, workflow, changespec: released.append(
            (project, workspace_num, workflow, changespec)
        ),
    )
    monkeypatch.setattr("sase.vcs_provider.get_vcs_provider", lambda _: provider)
    monkeypatch.setattr(
        "sase.ace.deltas.refresh_deltas_after_commits_change",
        lambda project, changespec, workspace: None,
    )
    monkeypatch.setattr(
        "sase.ace.timestamps.recording.generate_timestamp",
        lambda: "260430_120000",
    )

    ok, message = _rebase_task(
        "Test Feature",
        str(project_file),
        "proj",
        "New Parent",
        "Old Parent",
    )

    assert ok
    assert message == "Rebased onto New Parent"
    assert provider.rebased_to == "New Parent"
    assert released == [(str(project_file), 7, "rebase-Test Feature", "Test Feature")]

    content = project_file.read_text(encoding="utf-8")
    assert "PARENT: New Parent\n" in content
    assert "  [260430_120000] REBASE Old Parent -> New Parent\n" in content


# === Tests for get_eligible_parents_in_project ===

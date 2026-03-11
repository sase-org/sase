"""Tests for the rebase feature (PARENT field updates and eligible parents)."""

import tempfile
from pathlib import Path

from sase.status_state_machine import update_changespec_parent_atomic
from sase.status_state_machine.field_updates import apply_parent_update


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


# === Tests for apply_parent_update ===


def testapply_parent_update_existing_field() -> None:
    """Test updating an existing PARENT field."""
    lines = [
        "NAME: Test Feature\n",
        "DESCRIPTION:\n",
        "  A test feature\n",
        "PARENT: OldParent\n",
        "CL: http://cl/123\n",
        "STATUS: Ready\n",
    ]

    result = apply_parent_update(lines, "Test Feature", "NewParent")
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


# === Tests for get_eligible_parents_in_project ===

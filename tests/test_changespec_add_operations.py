"""Tests for adding ChangeSpecs to project files."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.ace.changespec.parser import parse_project_file
from sase.workflows.commit.patch_operations import add_changespec_to_project_file


def test_add_changespec_inherits_parent_hooks(tmp_path: Path) -> None:
    """Test that child ChangeSpec inherits hooks from parent."""
    # Create a project file with a parent ChangeSpec containing hooks
    parent_content = """NAME: parent_feature
DESCRIPTION:
  Parent description
PR: http://cl/11111
STATUS: Draft
HOOKS:
  !$sase_hg_presubmit
  sase_hg_lint
  bb_rabbit_test //foo:parent_test
"""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(parent_content)
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="child_feature",
                description="Child description",
                parent="parent_feature",
                pr_url="http://cl/22222",
                # initial_hooks contains !$sase_hg_presubmit (should NOT be duplicated)
                initial_hooks=["!$sase_hg_presubmit"],
            )

        assert result is not None

        with open(project_file, encoding="utf-8") as f:
            content = f.read()

        # Verify child ChangeSpec exists
        assert "NAME: child_feature_1" in content

        # Parse to verify hooks - find the child ChangeSpec
        changespecs = parse_project_file(project_file)
        child_cs = next(cs for cs in changespecs if cs.name == "child_feature_1")
        assert child_cs.hooks is not None

        # Get hook commands from the child
        child_hooks = [h.command for h in child_cs.hooks]

        # Should have: initial hook + inherited parent hooks (minus duplicate)
        assert "!$sase_hg_presubmit" in child_hooks  # From initial_hooks
        assert "sase_hg_lint" in child_hooks  # Inherited from parent
        assert "bb_rabbit_test //foo:parent_test" in child_hooks  # Inherited

        # !$sase_hg_presubmit should NOT be duplicated
        assert child_hooks.count("!$sase_hg_presubmit") == 1
    finally:
        os.unlink(project_file)


def test_add_changespec_inherits_parent_bug(tmp_path: Path) -> None:
    """Test that child ChangeSpec inherits BUG from parent."""
    # Create a project file with a parent ChangeSpec containing BUG
    parent_content = """NAME: parent_feature
DESCRIPTION:
  Parent description
BUG: http://b/12345678
PR: http://cl/11111
STATUS: Draft
"""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(parent_content)
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="child_feature",
                description="Child description",
                parent="parent_feature",
                pr_url="http://cl/22222",
                # No bug parameter - should inherit from parent
            )

        assert result is not None

        # Parse to verify BUG inheritance
        changespecs = parse_project_file(project_file)
        child_cs = next(cs for cs in changespecs if cs.name == "child_feature_1")

        # Child should have inherited parent's BUG
        assert child_cs.bug == "http://b/12345678"
    finally:
        os.unlink(project_file)


def test_add_changespec_initial_commit_plan_drawer(tmp_path: Path) -> None:
    """Plan path in position 5 of initial_commits tuple emits PLAN drawer."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="plan_feature",
                description="Has plan",
                parent=None,
                pr_url="http://cl/99999",
                initial_commits=[
                    (
                        1,
                        "[run] Initial Commit",
                        "~/chats/c.md",
                        "~/diffs/d.diff",
                        None,
                        "~/.sase/plans/my_plan.md",
                    )
                ],
            )

        assert result is not None

        changespecs = parse_project_file(project_file)
        cs = next(c for c in changespecs if c.name == "plan_feature_1")
        assert cs.commits is not None
        assert len(cs.commits) == 1
        assert cs.commits[0].plan == "~/.sase/plans/my_plan.md"
    finally:
        os.unlink(project_file)


def test_add_changespec_initial_commit_no_plan_drawer(tmp_path: Path) -> None:
    """4-element tuple (no plan_path) does not emit PLAN drawer."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="no_plan_feature",
                description="No plan",
                parent=None,
                pr_url="http://cl/88888",
                initial_commits=[
                    (1, "[run] Initial Commit", "~/chats/c.md", "~/diffs/d.diff")
                ],
            )

        assert result is not None

        changespecs = parse_project_file(project_file)
        cs = next(c for c in changespecs if c.name == "no_plan_feature_1")
        assert cs.commits is not None
        assert len(cs.commits) == 1
        assert cs.commits[0].plan is None
    finally:
        os.unlink(project_file)


def test_add_changespec_initial_commits_creates_timestamps(tmp_path: Path) -> None:
    """ChangeSpec with initial_commits includes a TIMESTAMPS section with COMMIT entries."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="ts_feature",
                description="Timestamps test",
                parent=None,
                initial_commits=[
                    (1, "[run] Initial Commit", "~/chats/c.md", "~/diffs/d.diff")
                ],
            )

        assert result is not None

        with open(project_file, encoding="utf-8") as f:
            content = f.read()

        assert "TIMESTAMPS:" in content
        # Structural check: COMMIT event with detail (1)
        assert "COMMIT " in content
        assert "(1)" in content
    finally:
        os.unlink(project_file)


def test_add_changespec_initial_commits_multiple_timestamps(tmp_path: Path) -> None:
    """Multiple initial commits produce multiple COMMIT timestamp lines in order."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="multi_ts",
                description="Multi timestamps",
                parent=None,
                initial_commits=[
                    (1, "First commit", "~/chats/c1.md", "~/diffs/d1.diff"),
                    ("2b", "Second commit", "~/chats/c2.md", "~/diffs/d2.diff"),
                ],
            )

        assert result is not None

        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Find TIMESTAMPS section and collect entries
        in_timestamps = False
        commit_details: list[str] = []
        for line in lines:
            if line.startswith("TIMESTAMPS:"):
                in_timestamps = True
                continue
            if in_timestamps and "COMMIT " in line:
                # Extract the detail portion after "COMMIT "
                idx = line.index("COMMIT ")
                detail = line[idx + len("COMMIT ") :].strip()
                commit_details.append(detail)
            elif in_timestamps and line.strip() and not line.startswith("  "):
                break

        assert commit_details == ["(1)", "(2b)"]
    finally:
        os.unlink(project_file)


def test_add_changespec_no_commits_no_timestamps(tmp_path: Path) -> None:
    """ChangeSpec without initial_commits has no TIMESTAMPS section."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="no_ts",
                description="No timestamps",
                parent=None,
            )

        assert result is not None

        with open(project_file, encoding="utf-8") as f:
            content = f.read()

        assert "TIMESTAMPS:" not in content
    finally:
        os.unlink(project_file)


def test_add_changespec_no_parent_bug_inherited_when_no_parent(tmp_path: Path) -> None:
    """Test that no BUG is inherited when there's no parent."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="orphan_feature",
                description="Orphan description",
                parent=None,  # No parent
                pr_url="http://cl/33333",
                # No bug parameter
            )

        assert result is not None

        changespecs = parse_project_file(project_file)
        cs = changespecs[0]

        # Should have no BUG since no parent and no explicit bug
        assert cs.bug is None
    finally:
        os.unlink(project_file)


def test_add_changespec_drops_parent_when_not_found_anywhere(tmp_path: Path) -> None:
    """Bogus parent (not in active file, not in archive) is dropped with a warning.

    Regression guard: previously ``PARENT: p4head`` (or any other unresolvable
    string) would be written verbatim into the generated ChangeSpec. Now the
    PARENT line is omitted entirely when the parent does not resolve.
    """
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="child_feature",
                description="Child description",
                parent="p4head",  # hg sentinel — not a ChangeSpec name
                pr_url="http://cl/22222",
            )

        assert result is not None

        with open(project_file, encoding="utf-8") as f:
            content = f.read()

        # The bogus PARENT value must not appear anywhere.
        assert "PARENT: p4head" not in content
        assert "PARENT:" not in content

        # Parser agrees the ChangeSpec has no parent.
        changespecs = parse_project_file(project_file)
        child_cs = next(c for c in changespecs if c.name == "child_feature_1")
        assert child_cs.parent is None
    finally:
        os.unlink(project_file)


def test_add_changespec_keeps_parent_when_in_archive(tmp_path: Path) -> None:
    """Parent in the archive (terminal CS) is valid — PARENT line is kept."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name
    archive_file = project_file[:-5] + "-archive.sase"
    with open(archive_file, "w", encoding="utf-8") as f:
        f.write(
            "NAME: submitted_parent\n"
            "DESCRIPTION:\n  Parent that was submitted\n"
            "STATUS: Submitted\n"
        )

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="child_feature",
                description="Child description",
                parent="submitted_parent",
                pr_url="http://cl/55555",
            )

        assert result is not None

        changespecs = parse_project_file(project_file)
        child_cs = next(c for c in changespecs if c.name == "child_feature_1")
        assert child_cs.parent == "submitted_parent"
    finally:
        os.unlink(project_file)
        if os.path.isfile(archive_file):
            os.unlink(archive_file)


def test_add_changespec_keeps_real_active_parent(tmp_path: Path) -> None:
    """A real active parent still produces ``PARENT: <name>`` at the right spot."""
    parent_content = (
        "NAME: parent_feature\n"
        "DESCRIPTION:\n  Parent description\n"
        "PR: http://cl/11111\n"
        "STATUS: Draft\n"
    )
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(parent_content)
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="child_feature",
                description="Child description",
                parent="parent_feature",
                pr_url="http://cl/22222",
            )

        assert result is not None

        changespecs = parse_project_file(project_file)
        child_cs = next(c for c in changespecs if c.name == "child_feature_1")
        assert child_cs.parent == "parent_feature"
    finally:
        os.unlink(project_file)

"""Tests for change_actions module."""

import os
import tempfile

from sase.change_actions import delete_proposal_entry


def testdelete_proposal_entry_file_not_found() -> None:
    """Test deleting from a non-existent file."""
    result = delete_proposal_entry("/nonexistent/path/file.gp", "my_feature", 1, "a")
    assert result is False


def testdelete_proposal_entry_wrong_cl_name() -> None:
    """Test that we don't delete entries from wrong ChangeSpec."""
    project_content = """NAME: feature_a
COMMITS:
  (1a) [fix]
      | DIFF: ~/.sase/diffs/a.diff

NAME: feature_b
COMMITS:
  (1a) [fix]
      | DIFF: ~/.sase/diffs/b.diff
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(project_content)
        project_file = f.name

    try:
        # Delete 1a from feature_a only
        result = delete_proposal_entry(project_file, "feature_a", 1, "a")
        assert result is True

        with open(project_file, encoding="utf-8") as f:
            content = f.read()

        # feature_a's 1a should be deleted
        lines = content.split("\n")
        in_feature_a = False
        in_feature_b = False
        found_1a_in_a = False
        found_1a_in_b = False

        for line in lines:
            if "NAME: feature_a" in line:
                in_feature_a = True
                in_feature_b = False
            elif "NAME: feature_b" in line:
                in_feature_a = False
                in_feature_b = True
            elif "(1a)" in line:
                if in_feature_a:
                    found_1a_in_a = True
                if in_feature_b:
                    found_1a_in_b = True

        # feature_a's 1a should be gone, feature_b's 1a should remain
        assert found_1a_in_a is False
        assert found_1a_in_b is True
    finally:
        os.unlink(project_file)

"""Tests for post-commit entry append utility."""

import json
from pathlib import Path

import pytest

from sase.workflows.commit_utils.post_commit import (
    PostCommitResult,
    append_post_commit_entry,
)


# ---------------------------------------------------------------------------
# append_post_commit_entry — missing env / files
# ---------------------------------------------------------------------------


def test_append_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)  # type: ignore[union-attr]
    monkeypatch.delenv("SASE_AGENT_PROJECT_FILE", raising=False)  # type: ignore[union-attr]
    monkeypatch.delenv("SASE_AGENT_CL_NAME", raising=False)  # type: ignore[union-attr]
    r = append_post_commit_entry(mode="commit")
    assert r == PostCommitResult(success=False)


def test_append_missing_commit_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(tmp_path / "proj.gp"))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]
    # project file exists but no commit_result.json
    (tmp_path / "proj.gp").write_text("NAME: my_cl\nSTATUS: Draft\n")
    r = append_post_commit_entry(mode="commit")
    assert r.success is False


def test_append_commit_result_null_result_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit_result.json with result=null (Mercurial amend) should still succeed."""
    proj = tmp_path / "proj.gp"
    proj.write_text("NAME: my_cl\nSTATUS: Draft\n")
    (tmp_path / "commit_result.json").write_text(
        json.dumps({"result": None, "message": "Agent changes"})
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(proj))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]
    r = append_post_commit_entry(mode="commit")
    assert r.success is True
    assert "COMMITS:" in proj.read_text()


# ---------------------------------------------------------------------------
# append_post_commit_entry — commit mode
# ---------------------------------------------------------------------------


def test_append_commit_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "proj.gp"
    proj.write_text("NAME: my_cl\nDESCRIPTION:\n  Desc\nSTATUS: Draft\n")

    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "method": "create_commit",
                "result": "abc123",
                "message": "Fix bug in parser",
                "diff_path": "~/.sase/diffs/test.diff",
            }
        )
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(proj))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]

    r = append_post_commit_entry(mode="commit")
    assert r.success is True
    assert r.entry_id == "1"  # commit mode now returns entry_id

    content = proj.read_text()
    assert "COMMITS:" in content
    assert "(1) Fix bug in parser" in content
    assert "| DIFF: ~/.sase/diffs/test.diff" in content


# ---------------------------------------------------------------------------
# append_post_commit_entry — proposal mode
# ---------------------------------------------------------------------------


def test_append_proposal_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "proj.gp"
    proj.write_text(
        "NAME: my_cl\nDESCRIPTION:\n  Desc\nSTATUS: Draft\n"
        "COMMITS:\n  (1) First commit\n"
    )

    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "method": "create_proposal",
                "result": "http://cl/12345",
                "message": "Proposed refactor",
            }
        )
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(proj))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]

    r = append_post_commit_entry(mode="proposal")
    assert r.success is True
    assert r.entry_id == "1a"

    content = proj.read_text()
    assert "(1a) Proposed refactor - (!: NEW PROPOSAL)" in content


def test_append_proposal_mode_no_existing_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "proj.gp"
    proj.write_text("NAME: my_cl\nDESCRIPTION:\n  Desc\nSTATUS: Draft\n")

    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "method": "create_proposal",
                "result": "http://cl/99999",
                "message": "Brand new proposal",
            }
        )
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(proj))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]

    r = append_post_commit_entry(mode="proposal")
    assert r.success is True
    assert r.entry_id == "0a"

    content = proj.read_text()
    assert "(0a) Brand new proposal - (!: NEW PROPOSAL)" in content


def test_append_proposal_with_diff_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "proj.gp"
    proj.write_text(
        "NAME: my_cl\nDESCRIPTION:\n  Desc\nSTATUS: Draft\n"
        "COMMITS:\n  (1) First commit\n"
    )

    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "method": "create_proposal",
                "result": "http://cl/123",
                "message": "Add tests",
                "diff_path": "~/.sase/diffs/prop.diff",
            }
        )
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(proj))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]

    r = append_post_commit_entry(mode="proposal")
    assert r.success is True
    assert r.entry_id == "1a"

    content = proj.read_text()
    assert "(1a) Add tests - (!: NEW PROPOSAL)" in content
    assert "| DIFF: ~/.sase/diffs/prop.diff" in content


def test_append_uses_first_line_of_multiline_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "proj.gp"
    proj.write_text("NAME: my_cl\nDESCRIPTION:\n  Desc\nSTATUS: Draft\n")

    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "method": "create_commit",
                "result": "abc",
                "message": "First line\nSecond line\nThird line",
            }
        )
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(proj))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]

    r = append_post_commit_entry(mode="commit")
    assert r.success is True

    content = proj.read_text()
    assert "(1) First line" in content
    assert "Second line" not in content

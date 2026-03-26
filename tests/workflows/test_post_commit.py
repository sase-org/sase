"""Tests for post-commit entry append utility."""

import json
from pathlib import Path

import pytest

from sase.workflows.commit_utils.post_commit import (
    PostCommitResult,
    _find_best_diff_path,
    _find_best_response_path,
    append_post_commit_entry,
)


# ---------------------------------------------------------------------------
# _find_best_diff_path / _find_best_response_path
# ---------------------------------------------------------------------------


def test_find_best_diff_path_empty_dir(tmp_path: Path) -> None:
    assert _find_best_diff_path(str(tmp_path)) is None


def test_find_best_diff_path_picks_last(tmp_path: Path) -> None:
    (tmp_path / "prompt_step_a.json").write_text(
        json.dumps({"diff_path": "/first.diff"})
    )
    (tmp_path / "prompt_step_b.json").write_text(
        json.dumps({"diff_path": "/second.diff"})
    )
    assert _find_best_diff_path(str(tmp_path)) == "/second.diff"


def test_find_best_diff_path_skips_empty(tmp_path: Path) -> None:
    (tmp_path / "prompt_step_a.json").write_text(
        json.dumps({"diff_path": "/good.diff"})
    )
    (tmp_path / "prompt_step_b.json").write_text(json.dumps({"diff_path": None}))
    assert _find_best_diff_path(str(tmp_path)) == "/good.diff"


def test_find_best_response_path(tmp_path: Path) -> None:
    (tmp_path / "prompt_step_x.json").write_text(
        json.dumps({"response_path": "/resp.json"})
    )
    assert _find_best_response_path(str(tmp_path)) == "/resp.json"


def test_find_best_response_path_empty(tmp_path: Path) -> None:
    assert _find_best_response_path(str(tmp_path)) is None


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


def test_append_commit_result_no_result_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(tmp_path / "proj.gp"))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]
    (tmp_path / "proj.gp").write_text("NAME: my_cl\nSTATUS: Draft\n")
    (tmp_path / "commit_result.json").write_text(json.dumps({"result": ""}))
    r = append_post_commit_entry(mode="commit")
    assert r.success is False


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
            }
        )
    )
    (tmp_path / "prompt_step_create.json").write_text(
        json.dumps({"diff_path": "~/.sase/diffs/test.diff"})
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(proj))  # type: ignore[union-attr]
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "my_cl")  # type: ignore[union-attr]

    r = append_post_commit_entry(mode="commit")
    assert r.success is True
    assert r.entry_id is None  # commit mode returns no entry_id

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
            }
        )
    )
    (tmp_path / "prompt_step_propose.json").write_text(
        json.dumps({"diff_path": "~/.sase/diffs/prop.diff"})
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

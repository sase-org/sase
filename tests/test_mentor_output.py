"""Tests for mentor output schema, storage, and acceptance state."""

import json
from pathlib import Path

from sase.ace.mentor_output import (
    MENTOR_OUTPUT_JSON_SCHEMA,
    MentorAcceptanceState,
    MentorComment,
    MentorOutput,
    load_acceptance_state,
    load_mentor_outputs_for_commit,
    _load_all_mentor_outputs,
    _load_mentor_output,
    save_acceptance_state,
    save_mentor_output,
)


# ── MentorComment / MentorOutput dataclasses ─────────────────────────────


def test_mentor_comment_fields() -> None:
    """Test MentorComment stores all fields."""
    comment = MentorComment(
        focus_name="comments",
        file_path="src/foo.py",
        line_number=42,
        description="Add docstring",
        severity="warning",
    )
    assert comment.focus_name == "comments"
    assert comment.file_path == "src/foo.py"
    assert comment.line_number == 42
    assert comment.severity == "warning"


def test_mentor_output_with_comments() -> None:
    """Test MentorOutput holds a list of comments."""
    output = MentorOutput(
        mentor_name="code_quality",
        profile_name="code",
        role="senior reviewer",
        comments=[
            MentorComment(
                focus_name="style",
                file_path="a.py",
                line_number=1,
                description="Fix",
                severity="suggestion",
            ),
        ],
    )
    assert output.mentor_name == "code_quality"
    assert len(output.comments) == 1


def test_mentor_output_empty_comments() -> None:
    """Test MentorOutput with no comments (PASSED case)."""
    output = MentorOutput(
        mentor_name="tests",
        profile_name="code",
        role="test specialist",
        comments=[],
    )
    assert len(output.comments) == 0


# ── JSON Schema ──────────────────────────────────────────────────────────


def test_json_schema_has_required_fields() -> None:
    """Test that the JSON schema declares all required top-level fields."""
    assert set(MENTOR_OUTPUT_JSON_SCHEMA["required"]) == {
        "mentor_name",
        "profile_name",
        "role",
        "comments",
    }


def test_json_schema_comment_severity_enum() -> None:
    """Test that severity is constrained to known values."""
    severity_schema = MENTOR_OUTPUT_JSON_SCHEMA["properties"]["comments"]["items"][
        "properties"
    ]["severity"]
    assert set(severity_schema["enum"]) == {"error", "warning", "suggestion"}


# ── Save / Load round-trip ───────────────────────────────────────────────


def _make_output() -> MentorOutput:
    return MentorOutput(
        mentor_name="code_quality",
        profile_name="code",
        role="senior reviewer",
        comments=[
            MentorComment(
                focus_name="comments",
                file_path="src/foo.py",
                line_number=42,
                description="Add docstring to process()",
                severity="warning",
            ),
            MentorComment(
                focus_name="shared_code",
                file_path="src/bar.py",
                line_number=10,
                description="Extract duplicated logic",
                severity="suggestion",
            ),
        ],
    )


def test_save_and_load_mentor_output(tmp_path: Path, monkeypatch: object) -> None:
    """Test save/load round-trip for mentor output."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    output = _make_output()
    path = save_mentor_output("my-cl", "code", "code_quality", "260321_120000", output)

    assert path.exists()
    loaded = _load_mentor_output(path)
    assert loaded.mentor_name == "code_quality"
    assert loaded.profile_name == "code"
    assert loaded.role == "senior reviewer"
    assert len(loaded.comments) == 2
    assert loaded.comments[0].focus_name == "comments"
    assert loaded.comments[1].line_number == 10


def test_load_all_mentor_outputs(tmp_path: Path, monkeypatch: object) -> None:
    """Test loading all outputs for a CL."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    output1 = _make_output()
    output2 = MentorOutput(
        mentor_name="tests",
        profile_name="code",
        role="test specialist",
        comments=[],
    )
    save_mentor_output("my-cl", "code", "code_quality", "260321_120000", output1)
    save_mentor_output("my-cl", "code", "tests", "260321_120001", output2)

    results = _load_all_mentor_outputs("my-cl")
    assert len(results) == 2
    names = [o.mentor_name for _, o in results]
    assert "code_quality" in names
    assert "tests" in names


def test_load_all_mentor_outputs_empty_dir(tmp_path: Path, monkeypatch: object) -> None:
    """Test loading from non-existent directory returns empty list."""
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path / "nonexistent"
    )
    assert _load_all_mentor_outputs("my-cl") == []


def test_load_all_skips_malformed(tmp_path: Path, monkeypatch: object) -> None:
    """Test that malformed JSON files are skipped."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    # Write a valid one
    save_mentor_output("cl", "p", "m", "ts1", _make_output())

    # Write a malformed one
    bad = tmp_path / "cl-p-bad-ts2.json"
    bad.write_text("{invalid json", encoding="utf-8")

    results = _load_all_mentor_outputs("cl")
    assert len(results) == 1


def test_load_all_skips_acceptance_files(tmp_path: Path, monkeypatch: object) -> None:
    """Test that acceptance state files are not loaded as mentor outputs."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    save_mentor_output("cl", "p", "m", "ts1", _make_output())

    # Create an acceptance file that matches the glob
    acceptance = tmp_path / "cl-1-acceptance.json"
    acceptance.write_text("{}", encoding="utf-8")

    results = _load_all_mentor_outputs("cl")
    assert len(results) == 1


def test_cl_name_with_slash(tmp_path: Path, monkeypatch: object) -> None:
    """Test that CL names with slashes are sanitized."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    output = _make_output()
    path = save_mentor_output("feat/branch", "code", "m", "ts", output)

    assert "feat_branch" in path.name
    loaded = _load_mentor_output(path)
    assert loaded.mentor_name == output.mentor_name


# ── load_mentor_outputs_for_commit ────────────────────────────────────────


def test_load_for_commit_no_false_positives(
    tmp_path: Path, monkeypatch: object
) -> None:
    """Short entry IDs must not collide with other filename components."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    # Timestamp "1" for entry_id "1"
    save_mentor_output("cl", "profile1", "mentor1", "1", _make_output())
    # Timestamp "21" — should NOT match entry_id "1"
    save_mentor_output("cl", "profile1", "mentor1", "21", _make_output())

    results = load_mentor_outputs_for_commit("cl", "1")
    assert len(results) == 1
    assert results[0][0].stem.endswith("-1")


# ── Acceptance state ─────────────────────────────────────────────────────


def test_acceptance_state_toggle() -> None:
    """Test toggling acceptance state."""
    state = MentorAcceptanceState()
    assert state.is_accepted("code", "quality", 0) is False

    result = state.toggle("code", "quality", 0)
    assert result is True
    assert state.is_accepted("code", "quality", 0) is True

    result = state.toggle("code", "quality", 0)
    assert result is False
    assert state.is_accepted("code", "quality", 0) is False


def test_acceptance_state_set() -> None:
    """Test explicit set_accepted."""
    state = MentorAcceptanceState()
    state.set_accepted("code", "quality", 0, True)
    assert state.is_accepted("code", "quality", 0) is True
    assert state.accepted_count == 1
    assert state.total_count == 1


def test_acceptance_state_counts() -> None:
    """Test accepted_count and total_count."""
    state = MentorAcceptanceState()
    state.set_accepted("code", "q", 0, True)
    state.set_accepted("code", "q", 1, False)
    state.set_accepted("code", "q", 2, True)

    assert state.accepted_count == 2
    assert state.total_count == 3


def test_save_and_load_acceptance_state(tmp_path: Path, monkeypatch: object) -> None:
    """Test save/load round-trip for acceptance state."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    state = MentorAcceptanceState()
    state.set_accepted("code", "quality", 0, True)
    state.set_accepted("code", "quality", 1, False)
    state.set_accepted("code", "tests", 0, True)

    save_acceptance_state("my-cl", "3", state)

    loaded = load_acceptance_state("my-cl", "3")
    assert loaded.is_accepted("code", "quality", 0) is True
    assert loaded.is_accepted("code", "quality", 1) is False
    assert loaded.is_accepted("code", "tests", 0) is True
    assert loaded.accepted_count == 2


def test_load_acceptance_state_missing(tmp_path: Path, monkeypatch: object) -> None:
    """Test loading non-existent acceptance state returns empty."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    state = load_acceptance_state("no-cl", "1")
    assert state.accepted_count == 0
    assert state.total_count == 0


def test_load_acceptance_state_malformed(tmp_path: Path, monkeypatch: object) -> None:
    """Test loading malformed acceptance state returns empty."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    bad = tmp_path / "cl-1-acceptance.json"
    bad.write_text("not valid json", encoding="utf-8")

    state = load_acceptance_state("cl", "1")
    assert state.accepted_count == 0

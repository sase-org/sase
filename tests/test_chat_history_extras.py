"""Tests for the chat_history_extras module."""

import json
import os
import tempfile

from sase.chat_history_extras import (
    _format_plan_feedback,
    _format_qa_log,
    _read_jsonl,
    format_extra_sections,
)


def test_read_jsonl_missing_file() -> None:
    """Returns empty list when file doesn't exist."""
    assert _read_jsonl("/nonexistent/path.jsonl") == []


def test_read_jsonl_valid() -> None:
    """Parses valid JSONL lines."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"a": 1}) + "\n")
        f.write(json.dumps({"b": 2}) + "\n")
        path = f.name
    try:
        records = _read_jsonl(path)
        assert len(records) == 2
        assert records[0] == {"a": 1}
        assert records[1] == {"b": 2}
    finally:
        os.unlink(path)


def test_read_jsonl_skips_bad_lines() -> None:
    """Skips malformed lines without raising."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"ok": True}) + "\n")
        f.write("not valid json\n")
        f.write(json.dumps({"also_ok": True}) + "\n")
        path = f.name
    try:
        records = _read_jsonl(path)
        assert len(records) == 2
    finally:
        os.unlink(path)


def test_format_plan_feedback_empty() -> None:
    """Returns None when no plan_feedback.jsonl exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert _format_plan_feedback(tmpdir) is None


def test_format_plan_feedback_single_round() -> None:
    """Formats a single feedback round."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "plan_feedback.jsonl")
        with open(path, "w") as f:
            f.write(
                json.dumps(
                    {"round": 0, "feedback": "Add error handling", "timestamp": 1.0}
                )
                + "\n"
            )

        result = _format_plan_feedback(tmpdir)
        assert result is not None
        assert "## Plan Feedback" in result
        assert "### Round 1" in result
        assert "> Add error handling" in result


def test_format_plan_feedback_multiple_rounds() -> None:
    """Formats multiple feedback rounds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "plan_feedback.jsonl")
        with open(path, "w") as f:
            f.write(
                json.dumps({"round": 0, "feedback": "First feedback", "timestamp": 1.0})
                + "\n"
            )
            f.write(
                json.dumps(
                    {"round": 1, "feedback": "Second feedback", "timestamp": 2.0}
                )
                + "\n"
            )

        result = _format_plan_feedback(tmpdir)
        assert result is not None
        assert "### Round 1" in result
        assert "### Round 2" in result
        assert "> First feedback" in result
        assert "> Second feedback" in result


def test_format_qa_log_empty() -> None:
    """Returns None when no qa_log.jsonl exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert _format_qa_log(tmpdir) is None


def test_format_qa_log_single_question() -> None:
    """Formats a single Q&A entry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "qa_log.jsonl")
        record = {
            "questions": [{"question": "Which DB?"}],
            "answers": [{"question": "Which DB?", "selected": ["PostgreSQL"]}],
            "global_note": "",
            "timestamp": 1.0,
        }
        with open(path, "w") as f:
            f.write(json.dumps(record) + "\n")

        result = _format_qa_log(tmpdir)
        assert result is not None
        assert "## Questions & Answers" in result
        assert "### Q1: Which DB?" in result
        assert "**Selected:** PostgreSQL" in result


def test_format_qa_log_with_global_note() -> None:
    """Includes global note when present."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "qa_log.jsonl")
        record = {
            "questions": [],
            "answers": [{"question": "Color?", "selected": ["Blue"]}],
            "global_note": "Please use dark theme",
            "timestamp": 1.0,
        }
        with open(path, "w") as f:
            f.write(json.dumps(record) + "\n")

        result = _format_qa_log(tmpdir)
        assert result is not None
        assert "**Global note:** Please use dark theme" in result


def test_format_qa_log_with_custom_feedback() -> None:
    """Includes custom feedback when present."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "qa_log.jsonl")
        record = {
            "questions": [],
            "answers": [
                {
                    "question": "Approach?",
                    "selected": ["Option A"],
                    "custom_feedback": "But modify X",
                }
            ],
            "global_note": "",
            "timestamp": 1.0,
        }
        with open(path, "w") as f:
            f.write(json.dumps(record) + "\n")

        result = _format_qa_log(tmpdir)
        assert result is not None
        assert "**Custom feedback:** But modify X" in result


def test_format_extra_sections_none_when_empty() -> None:
    """Returns None when no JSONL files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert format_extra_sections(tmpdir) is None


def test_format_extra_sections_combined() -> None:
    """Combines plan feedback and Q&A into one string."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write plan feedback
        with open(os.path.join(tmpdir, "plan_feedback.jsonl"), "w") as f:
            f.write(
                json.dumps({"round": 0, "feedback": "Fix it", "timestamp": 1.0}) + "\n"
            )

        # Write QA log
        record = {
            "questions": [],
            "answers": [{"question": "Which?", "selected": ["A"]}],
            "global_note": "",
            "timestamp": 2.0,
        }
        with open(os.path.join(tmpdir, "qa_log.jsonl"), "w") as f:
            f.write(json.dumps(record) + "\n")

        result = format_extra_sections(tmpdir)
        assert result is not None
        assert "## Plan Feedback" in result
        assert "## Questions & Answers" in result
        # Plan feedback comes first
        pf_pos = result.index("## Plan Feedback")
        qa_pos = result.index("## Questions & Answers")
        assert pf_pos < qa_pos


def test_format_qa_log_multiple_records_number_sequentially() -> None:
    """Question numbers increment across multiple JSONL records."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "qa_log.jsonl")
        record1 = {
            "questions": [],
            "answers": [{"question": "First?", "selected": ["A"]}],
            "global_note": "",
            "timestamp": 1.0,
        }
        record2 = {
            "questions": [],
            "answers": [{"question": "Second?", "selected": ["B"]}],
            "global_note": "",
            "timestamp": 2.0,
        }
        with open(path, "w") as f:
            f.write(json.dumps(record1) + "\n")
            f.write(json.dumps(record2) + "\n")

        result = _format_qa_log(tmpdir)
        assert result is not None
        assert "### Q1: First?" in result
        assert "### Q2: Second?" in result

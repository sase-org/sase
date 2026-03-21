"""Tests for mentor workflow JSON parsing (_parse_mentor_json)."""

from sase.workflows.mentor import _parse_mentor_json


def test_parse_valid_json_with_comments() -> None:
    """Test parsing valid JSON with comments from code fence."""
    response = """Here are my findings:

```json
{
  "mentor_name": "code_quality",
  "profile_name": "code",
  "role": "senior reviewer",
  "comments": [
    {
      "focus_name": "comments",
      "file_path": "src/foo.py",
      "line_number": 42,
      "description": "Add docstring",
      "severity": "warning"
    }
  ]
}
```
"""
    result = _parse_mentor_json(response, "code", "code_quality")
    assert result is not None
    assert result.mentor_name == "code_quality"
    assert result.profile_name == "code"
    assert result.role == "senior reviewer"
    assert len(result.comments) == 1
    assert result.comments[0].focus_name == "comments"
    assert result.comments[0].file_path == "src/foo.py"
    assert result.comments[0].line_number == 42
    assert result.comments[0].severity == "warning"


def test_parse_valid_json_empty_comments() -> None:
    """Test parsing valid JSON with empty comments list (PASSED case)."""
    response = """```json
{
  "mentor_name": "tests",
  "profile_name": "code",
  "role": "test specialist",
  "comments": []
}
```"""
    result = _parse_mentor_json(response, "code", "tests")
    assert result is not None
    assert len(result.comments) == 0


def test_parse_invalid_json_returns_none() -> None:
    """Test that invalid JSON response returns None."""
    response = "This is not JSON at all, just plain text feedback."
    result = _parse_mentor_json(response, "code", "quality")
    assert result is None


def test_parse_json_missing_comments_key() -> None:
    """Test parsing JSON that is missing the comments key."""
    response = """```json
{
  "mentor_name": "quality",
  "profile_name": "code",
  "role": "reviewer"
}
```"""
    result = _parse_mentor_json(response, "code", "quality")
    assert result is not None
    assert len(result.comments) == 0


def test_parse_json_with_invalid_comment_fields() -> None:
    """Test parsing JSON where comment is missing required fields."""
    response = """```json
{
  "mentor_name": "quality",
  "profile_name": "code",
  "role": "reviewer",
  "comments": [
    {
      "focus_name": "style"
    }
  ]
}
```"""
    result = _parse_mentor_json(response, "code", "quality")
    assert result is None


def test_parse_json_falls_back_to_args_for_names() -> None:
    """Test that profile/mentor names fall back to function arguments."""
    response = """```json
{
  "comments": []
}
```"""
    result = _parse_mentor_json(response, "my_profile", "my_mentor")
    assert result is not None
    assert result.mentor_name == "my_mentor"
    assert result.profile_name == "my_profile"
    assert result.role == ""


def test_parse_json_not_an_object() -> None:
    """Test that a JSON array response returns None."""
    response = """```json
[1, 2, 3]
```"""
    result = _parse_mentor_json(response, "code", "quality")
    assert result is None


def test_parse_multiple_comments() -> None:
    """Test parsing JSON with multiple comments."""
    response = """```json
{
  "mentor_name": "code_quality",
  "profile_name": "code",
  "role": "senior reviewer",
  "comments": [
    {
      "focus_name": "comments",
      "file_path": "src/a.py",
      "line_number": 10,
      "description": "Add docstring",
      "severity": "warning"
    },
    {
      "focus_name": "shared_code",
      "file_path": "src/b.py",
      "line_number": 20,
      "description": "Extract duplicate",
      "severity": "suggestion"
    },
    {
      "focus_name": "visibility",
      "file_path": "src/c.py",
      "line_number": 30,
      "description": "Make private",
      "severity": "error"
    }
  ]
}
```"""
    result = _parse_mentor_json(response, "code", "code_quality")
    assert result is not None
    assert len(result.comments) == 3
    assert result.comments[0].severity == "warning"
    assert result.comments[1].severity == "suggestion"
    assert result.comments[2].severity == "error"

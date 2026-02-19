"""Tests for git_submit module."""

from unittest.mock import MagicMock

from sase.git_submit import _changespec_name_to_branch


def _make_changespec(name: str, project_basename: str) -> MagicMock:
    """Create a mock ChangeSpec with the given name and project_basename."""
    cs = MagicMock()
    cs.name = name
    cs.project_basename = project_basename
    return cs


def test_standard_case() -> None:
    """Standard case: strip prefix, strip __N suffix, underscores to hyphens."""
    cs = _make_changespec("sase_dull_basin__1", "sase")
    assert _changespec_name_to_branch(cs) == "dull-basin"


def test_no_suffix() -> None:
    """Name without __N suffix is handled correctly."""
    cs = _make_changespec("sase_dull_basin", "sase")
    assert _changespec_name_to_branch(cs) == "dull-basin"


def test_no_prefix() -> None:
    """Name without project prefix falls through to hyphen conversion."""
    cs = _make_changespec("dull_basin__1", "sase")
    assert _changespec_name_to_branch(cs) == "dull-basin"


def test_single_word() -> None:
    """Single-word branch name after stripping prefix and suffix."""
    cs = _make_changespec("sase_feature__1", "sase")
    assert _changespec_name_to_branch(cs) == "feature"


def test_multi_word_branch() -> None:
    """Branch with three words converts correctly."""
    cs = _make_changespec("myproj_foo_bar_baz__3", "myproj")
    assert _changespec_name_to_branch(cs) == "foo-bar-baz"


def test_higher_suffix_number() -> None:
    """Higher revert suffix numbers are stripped correctly."""
    cs = _make_changespec("sase_cool_thing__42", "sase")
    assert _changespec_name_to_branch(cs) == "cool-thing"

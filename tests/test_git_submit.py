"""Tests for changespec_name_to_branch utility."""

from sase.sase_utils import changespec_name_to_branch


def test_standard_case() -> None:
    """Standard case: strip prefix, strip __N suffix, underscores to hyphens."""
    assert changespec_name_to_branch("sase_dull_basin__1", "sase") == "dull-basin"


def test_no_suffix() -> None:
    """Name without __N suffix is handled correctly."""
    assert changespec_name_to_branch("sase_dull_basin", "sase") == "dull-basin"


def test_no_prefix() -> None:
    """Name without project prefix falls through to hyphen conversion."""
    assert changespec_name_to_branch("dull_basin__1", "sase") == "dull-basin"


def test_single_word() -> None:
    """Single-word branch name after stripping prefix and suffix."""
    assert changespec_name_to_branch("sase_feature__1", "sase") == "feature"


def test_multi_word_branch() -> None:
    """Branch with three words converts correctly."""
    assert changespec_name_to_branch("myproj_foo_bar_baz__3", "myproj") == "foo-bar-baz"


def test_higher_suffix_number() -> None:
    """Higher revert suffix numbers are stripped correctly."""
    assert changespec_name_to_branch("sase_cool_thing__42", "sase") == "cool-thing"

"""Tests for changespec_name_to_branch utility."""

from sase.sase_utils import changespec_name_to_branch


def test_no_prefix() -> None:
    """Name without project prefix falls through to hyphen conversion."""
    assert changespec_name_to_branch("dull_basin__1", "sase") == "dull-basin"

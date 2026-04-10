"""Tests for changespec_names_match()."""

from sase.core.changespec import changespec_names_match


class TestChangespecNamesMatch:
    def test_exact_match(self) -> None:
        assert changespec_names_match("tcpm_launch_tests", "tcpm_launch_tests")

    def test_suffix_on_first_arg(self) -> None:
        assert changespec_names_match("tcpm_launch_tests_1", "tcpm_launch_tests")

    def test_suffix_on_second_arg(self) -> None:
        assert changespec_names_match("tcpm_launch_tests", "tcpm_launch_tests_1")

    def test_legacy_double_underscore_suffix(self) -> None:
        assert changespec_names_match("tcpm_launch_tests__2", "tcpm_launch_tests")

    def test_different_bases_same_suffix(self) -> None:
        assert not changespec_names_match("foo_1", "bar_1")

    def test_two_different_suffixes_same_base(self) -> None:
        assert not changespec_names_match("foo_1", "foo_2")

    def test_no_suffix_different_names(self) -> None:
        assert not changespec_names_match("foo", "bar")

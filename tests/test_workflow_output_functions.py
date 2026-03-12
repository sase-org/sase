"""Snapshot tests for pure functions in xprompt.workflow_output."""

from inline_snapshot import snapshot

from sase.xprompt.workflow_output import _format_value, get_substep_suffix


class TestGetSubstepSuffix:
    def test_single_letters(self) -> None:
        assert get_substep_suffix(0) == snapshot("a")
        assert get_substep_suffix(1) == snapshot("b")
        assert get_substep_suffix(25) == snapshot("z")

    def test_double_letters(self) -> None:
        assert get_substep_suffix(26) == snapshot("aa")
        assert get_substep_suffix(27) == snapshot("ab")
        assert get_substep_suffix(51) == snapshot("az")
        assert get_substep_suffix(52) == snapshot("ba")


class TestFormatValue:
    def test_short_string(self) -> None:
        assert _format_value("hello") == snapshot('"hello"')

    def test_long_string_truncated(self) -> None:
        long_str = "a" * 50
        result = _format_value(long_str)
        assert result == snapshot('"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa..."')

    def test_short_list(self) -> None:
        assert _format_value([1, 2, 3]) == snapshot("[1, 2, 3]")

    def test_long_list_summarized(self) -> None:
        assert _format_value([1, 2, 3, 4, 5]) == snapshot("[1, 2, ... (5 items)]")

    def test_short_dict(self) -> None:
        assert _format_value({"a": 1}) == snapshot("{'a': 1}")

    def test_large_dict_summarized(self) -> None:
        assert _format_value({"a": 1, "b": 2, "c": 3}) == snapshot("{...} (3 keys)")

    def test_integer(self) -> None:
        assert _format_value(42) == snapshot("42")

    def test_none(self) -> None:
        assert _format_value(None) == snapshot("None")

    def test_bool(self) -> None:
        assert _format_value(True) == snapshot("True")

    def test_empty_string(self) -> None:
        assert _format_value("") == snapshot('""')

    def test_empty_list(self) -> None:
        assert _format_value([]) == snapshot("[]")

    def test_empty_dict(self) -> None:
        assert _format_value({}) == snapshot("{}")

    def test_boundary_string_length_40(self) -> None:
        s = "a" * 40
        assert _format_value(s) == snapshot(
            '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"'
        )

    def test_boundary_string_length_39(self) -> None:
        s = "a" * 39
        assert _format_value(s) == snapshot('"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"')

    def test_two_element_dict(self) -> None:
        assert _format_value({"x": 1, "y": 2}) == snapshot("{'x': 1, 'y': 2}")

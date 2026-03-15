"""Tests for xprompt alias resolution."""

from unittest.mock import patch

from sase.xprompt.processor import resolve_xprompt_aliases


def _mock_config(aliases: dict[str, str]) -> dict:
    return {"xprompt_aliases": aliases}


class TestResolveXpromptAliases:
    """Tests for resolve_xprompt_aliases()."""

    def test_no_aliases_configured(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value={"xprompt_aliases": {}},
        ):
            assert resolve_xprompt_aliases("hello #foo") == "hello #foo"

    def test_missing_aliases_key(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value={},
        ):
            assert resolve_xprompt_aliases("hello #foo") == "hello #foo"

    def test_simple_replacement(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            assert resolve_xprompt_aliases("#gh_sase") == "#gh:sase"

    def test_start_of_line(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("#gh_sase do something")
            assert result == "#gh:sase do something"

    def test_after_whitespace(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("run #gh_sase now")
            assert result == "run #gh:sase now"

    def test_after_open_paren(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("(#gh_sase)")
            assert result == "(#gh:sase)"

    def test_no_match_inside_word(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"foo": "bar"}),
        ):
            # "x#foo" should not match because # is preceded by a letter
            result = resolve_xprompt_aliases("x#foo")
            assert result == "x#foo"

    def test_no_partial_name_match(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh": "github"}),
        ):
            # #gh_sase should NOT be matched by alias "gh" due to negative lookahead
            result = resolve_xprompt_aliases("#gh_sase")
            assert result == "#gh_sase"

    def test_multiple_aliases(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase", "gh_dot": "gh:dotfiles"}),
        ):
            result = resolve_xprompt_aliases("#gh_sase and #gh_dot")
            assert result == "#gh:sase and #gh:dotfiles"

    def test_idempotent(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            first = resolve_xprompt_aliases("#gh_sase")
            second = resolve_xprompt_aliases(first)
            assert first == second == "#gh:sase"

    def test_no_hash_early_return(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("no hash here")
            assert result == "no hash here"

    def test_multiple_occurrences(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("#gh_sase #gh_sase")
            assert result == "#gh:sase #gh:sase"

    def test_after_newline(self) -> None:
        with patch(
            "sase.config.load_merged_config",
            return_value=_mock_config({"gh_sase": "gh:sase"}),
        ):
            result = resolve_xprompt_aliases("line1\n#gh_sase")
            assert result == "line1\n#gh:sase"

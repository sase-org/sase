"""Unit tests for portable CLI parser help assertions."""

from __future__ import annotations

import pytest

from tests.main.parser_help_helpers import assert_metavar_option_documented


def test_assert_metavar_option_documented_accepts_both_argparse_spellings() -> None:
    pre_313 = "-m MODEL, --model MODEL  Model or alias for the successor"
    post_313 = "-m, --model MODEL  Model or alias for the successor"

    assert_metavar_option_documented(pre_313, "-m", "--model", "MODEL")
    assert_metavar_option_documented(post_313, "-m", "--model", "MODEL")


def test_assert_metavar_option_documented_rejects_missing_option_or_metavar() -> None:
    help_text = "-m, --model TOKEN  Model or alias for the successor"

    with pytest.raises(AssertionError, match="option was not documented"):
        assert_metavar_option_documented(help_text, "-n", "--name", "TOKEN")
    with pytest.raises(AssertionError, match="option was not documented"):
        assert_metavar_option_documented(help_text, "-m", "--model", "MODEL")

"""Tests for the source-preserving config YAML writer."""

from __future__ import annotations

import difflib
from unittest.mock import patch

import yaml

from sase.config.edit import set_key, unset_key


def _diff_changed_lines(old: str, new: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile="a/sase.yml",
            tofile="b/sase.yml",
        )
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


def test_set_key_preserves_comments_and_order() -> None:
    """Setting a value keeps surrounding comments, key order, and quoting."""
    text = (
        "# top comment\n"
        'timezone: "US/Pacific"  # tz\n'
        "axe:\n"
        "  max_hook_runners: 3  # runners\n"
    )
    result = set_key(text, ("axe", "max_hook_runners"), 9)
    assert "# top comment" in result
    assert "# tz" in result
    assert "# runners" in result
    assert "max_hook_runners: 9" in result
    # Quoting style of the untouched scalar is preserved.
    assert '"US/Pacific"' in result


def test_set_key_changes_only_existing_scalar_line() -> None:
    """A scalar edit does not reflow unrelated YAML constructs."""
    text = (
        "github_orgs:\n"
        "  - sase-org\n"
        "linked_repos:\n"
        "  - name: core\n"
        "xprompts:\n"
        "  ship:\n"
        "    content: >-\n"
        "      one long folded line\n"
        "      that must stay folded\n"
        'flow: { type: line, default: "feature" }\n'
        "llm_provider:\n"
        "  model_aliases:\n"
        "    claude_coder: sonnet  # alias\n"
        "    worker: codex/o3\n"
    )
    expected = text.replace(
        "    claude_coder: sonnet  # alias\n",
        "    claude_coder: opus  # alias\n",
    )

    result = set_key(text, ("llm_provider", "model_aliases", "claude_coder"), "opus")

    assert result == expected
    assert _diff_changed_lines(text, result) == [
        "-    claude_coder: sonnet  # alias",
        "+    claude_coder: opus  # alias",
    ]


def test_set_key_preserves_existing_quote_style_on_scalar_replace() -> None:
    result = set_key('timezone: "US/Pacific"  # tz\n', ("timezone",), "UTC")
    assert result == 'timezone: "UTC"  # tz\n'


def test_set_key_inserts_one_alias_line_under_existing_mapping() -> None:
    text = "llm_provider:\n  model_aliases:\n    coder: sonnet\n    worker: codex/o3\n"
    expected = (
        "llm_provider:\n"
        "  model_aliases:\n"
        "    coder: sonnet\n"
        "    worker: codex/o3\n"
        "    reviewer: opus\n"
    )

    result = set_key(text, ("llm_provider", "model_aliases", "reviewer"), "opus")

    assert result == expected
    assert _diff_changed_lines(text, result) == ["+    reviewer: opus"]


def test_set_key_creates_missing_alias_section_without_touching_existing_text() -> None:
    text = (
        "github_orgs:\n"
        "  - sase-org\n"
        "xprompts:\n"
        "  ship:\n"
        "    content: >-\n"
        "      keep\n"
        "      wrapped\n"
    )
    expected = text + "llm_provider:\n" + "  model_aliases:\n" + "    reviewer: opus\n"

    result = set_key(text, ("llm_provider", "model_aliases", "reviewer"), "opus")

    assert result == expected
    assert _diff_changed_lines(text, result) == [
        "+llm_provider:",
        "+  model_aliases:",
        "+    reviewer: opus",
    ]


def test_set_key_creates_intermediate_mappings() -> None:
    """Setting a nested key on an empty document builds the parent mapping."""
    result = set_key("", ("axe", "max_hook_runners"), 5)
    assert yaml.safe_load(result) == {"axe": {"max_hook_runners": 5}}


def test_unset_key_removes_only_the_target() -> None:
    """Unsetting removes the key and its inline comment, keeping the rest."""
    text = (
        "# top comment\n"
        "timezone: US/Pacific  # tz\n"
        "axe:\n"
        "  max_hook_runners: 3  # runners\n"
    )
    result = unset_key(text, ("timezone",))
    assert "timezone" not in result
    assert "# top comment" in result
    assert "max_hook_runners: 3" in result


def test_unset_key_removes_only_target_alias_line() -> None:
    text = (
        "llm_provider:\n"
        "  model_aliases:\n"
        "    coder: sonnet  # remove\n"
        "    worker: codex/o3\n"
    )
    expected = "llm_provider:\n  model_aliases:\n    worker: codex/o3\n"

    result = unset_key(text, ("llm_provider", "model_aliases", "coder"))

    assert result == expected
    assert _diff_changed_lines(text, result) == ["-    coder: sonnet  # remove"]


def test_unset_key_missing_path_is_noop() -> None:
    """Unsetting an absent key returns the original text unchanged."""
    text = "timezone: US/Pacific\n"
    assert unset_key(text, ("nope",)) == text
    assert unset_key(text, ("a", "b")) == text


def test_set_key_declined_value_shape_falls_back_to_round_trip() -> None:
    text = "llm_provider:\n  model_aliases:\n    coder: sonnet\n"
    result = set_key(
        text,
        ("llm_provider", "model_aliases"),
        {"coder": "opus", "reviewer": "sonnet"},
    )
    assert yaml.safe_load(result) == {
        "llm_provider": {"model_aliases": {"coder": "opus", "reviewer": "sonnet"}}
    }


def test_set_key_safety_rejection_uses_round_trip_fallback() -> None:
    text = "llm_provider:\n  model_aliases:\n    coder: sonnet\n"
    key_path = ("llm_provider", "model_aliases", "coder")
    with (
        patch(
            "sase.config._edit_yaml_surgical._parsed_edit_matches", return_value=False
        ),
        patch(
            "sase.config._edit_yaml._set_key_round_trip", return_value="fallback\n"
        ) as fallback,
    ):
        assert set_key(text, key_path, "opus") == "fallback\n"
    fallback.assert_called_once_with(text, key_path, "opus")

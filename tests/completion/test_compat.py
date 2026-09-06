"""Tests for compatibility-only completion discovery marks."""

from __future__ import annotations

import argparse

from sase.completion.compat import (
    get_completion_compat_aliases,
    get_completion_compat_choices,
    get_completion_compat_option_strings,
    mark_patch_target_compat_option_strings,
    set_completion_compat_aliases,
    set_completion_compat_choices,
    set_completion_compat_option_strings,
)


def test_command_alias_marks_accumulate() -> None:
    parser = argparse.ArgumentParser()
    set_completion_compat_aliases(parser, "changespec")
    set_completion_compat_aliases(parser, "vcs")
    assert get_completion_compat_aliases(parser) == frozenset({"changespec", "vcs"})


def test_option_string_marks_and_patch_target_helper() -> None:
    parser = argparse.ArgumentParser()
    with_canonical_short = parser.add_argument(
        "-p", "--patch", "-c", "--changespec", dest="patch"
    )
    mark_patch_target_compat_option_strings(with_canonical_short)
    assert get_completion_compat_option_strings(with_canonical_short) == frozenset(
        {"-c", "--changespec"}
    )

    parser = argparse.ArgumentParser()
    short_is_canonical = parser.add_argument(
        "-c", "--patch", "--changespec", dest="patch"
    )
    mark_patch_target_compat_option_strings(short_is_canonical)
    assert get_completion_compat_option_strings(short_is_canonical) == frozenset(
        {"--changespec"}
    )


def test_choice_marks_and_explicit_option_strings() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_argument(
        "-t",
        "--tab",
        choices=("artifacts", "changespecs", "patches", "agents"),
    )
    set_completion_compat_choices(action, "changespecs", "patches")
    set_completion_compat_option_strings(action, "--unused")
    assert get_completion_compat_choices(action) == frozenset(
        {"changespecs", "patches"}
    )
    assert "--unused" in get_completion_compat_option_strings(action)

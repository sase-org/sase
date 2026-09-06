"""Mark compatibility-only CLI spellings so completion generation can omit them.

Runtime parsers keep accepting the old names. Completions, however, should
offer only canonical commands, option strings, and choice values. Call these
helpers at the argparse registration that still owns the alias.
"""

from __future__ import annotations

import argparse
from typing import Final

_ALIASES_ATTR: Final = "_sase_completion_compat_aliases"
_OPTION_STRINGS_ATTR: Final = "_sase_completion_compat_option_strings"
_CHOICES_ATTR: Final = "_sase_completion_compat_choices"
_PATCH_COMPAT_LONG_OPTIONS: Final = frozenset({"--changespec", "--cl"})


def set_completion_compat_aliases(
    parser: argparse.ArgumentParser, *aliases: str
) -> None:
    """Record command aliases that must not appear in generated completions."""
    setattr(
        parser,
        _ALIASES_ATTR,
        get_completion_compat_aliases(parser) | frozenset(aliases),
    )


def get_completion_compat_aliases(parser: argparse.ArgumentParser) -> frozenset[str]:
    """Return command aliases marked as compatibility-only on *parser*."""
    return frozenset(getattr(parser, _ALIASES_ATTR, ()))


def set_completion_compat_option_strings(
    action: argparse.Action, *strings: str
) -> None:
    """Record option strings that must not appear in generated completions."""
    setattr(
        action,
        _OPTION_STRINGS_ATTR,
        get_completion_compat_option_strings(action) | frozenset(strings),
    )


def get_completion_compat_option_strings(action: argparse.Action) -> frozenset[str]:
    """Return option strings marked as compatibility-only on *action*."""
    return frozenset(getattr(action, _OPTION_STRINGS_ATTR, ()))


def set_completion_compat_choices(action: argparse.Action, *choices: str) -> None:
    """Record choice values that must not appear in generated completions."""
    setattr(
        action,
        _CHOICES_ATTR,
        get_completion_compat_choices(action) | frozenset(choices),
    )


def get_completion_compat_choices(action: argparse.Action) -> frozenset[str]:
    """Return choice values marked as compatibility-only on *action*."""
    return frozenset(getattr(action, _CHOICES_ATTR, ()))


def mark_patch_target_compat_option_strings(action: argparse.Action) -> None:
    """Hide ChangeSpec option spellings on a Patch-target argparse action.

    ``--changespec`` and ``--cl`` are always compatibility-only. ``-c`` is
    hidden only when a canonical short form (``-p`` or ``-P``) is also
    registered, so ``-c/--patch`` keeps its short option when that is the
    canonical spelling.
    """
    present = frozenset(action.option_strings)
    hidden = present & _PATCH_COMPAT_LONG_OPTIONS
    if "-c" in present and present & {"-p", "-P"}:
        hidden = hidden | {"-c"}
    if hidden:
        set_completion_compat_option_strings(action, *sorted(hidden))


__all__ = [
    "get_completion_compat_aliases",
    "get_completion_compat_choices",
    "get_completion_compat_option_strings",
    "mark_patch_target_compat_option_strings",
    "set_completion_compat_aliases",
    "set_completion_compat_choices",
    "set_completion_compat_option_strings",
]

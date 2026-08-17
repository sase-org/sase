"""Root-level options parsed from argv before argparse runs."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Final, NoReturn


ENABLE_FEATURE_OPTION_STRINGS: Final[tuple[str, ...]] = ("-f", "--enable-feature")
DISABLE_FEATURE_OPTION_STRINGS: Final[tuple[str, ...]] = ("-F", "--disable-feature")
FEATURE_FLAG_OPTION_STRINGS: Final[tuple[tuple[str, ...], ...]] = (
    ENABLE_FEATURE_OPTION_STRINGS,
    DISABLE_FEATURE_OPTION_STRINGS,
)

_ENABLE_HELP = "Enable a registered feature flag for this invocation"
_DISABLE_HELP = "Disable a registered feature flag for this invocation"


class _GlobalOptionError(Exception):
    """Raised when a leading root-level option cannot be consumed."""


def register_global_feature_flag_options(parser: argparse.ArgumentParser) -> None:
    """Register root ``-f``/``-F`` options for help and completion."""
    from sase.completion.kinds import ValueKind, set_completion_kind

    enable_strings, disable_strings = FEATURE_FLAG_OPTION_STRINGS
    enable = parser.add_argument(
        *enable_strings,
        action="append",
        dest="enable_feature",
        metavar="<flag>",
        default=argparse.SUPPRESS,
        help=_ENABLE_HELP,
    )
    disable = parser.add_argument(
        *disable_strings,
        action="append",
        dest="disable_feature",
        metavar="<flag>",
        default=argparse.SUPPRESS,
        help=_DISABLE_HELP,
    )
    set_completion_kind(enable, ValueKind.FLAG)
    set_completion_kind(disable, ValueKind.FLAG)


def _extract_leading_feature_flag_options(
    argv: Sequence[str],
) -> tuple[dict[str, bool], list[str]]:
    """Return leading feature-flag options and the remaining argv tokens.

    Accepts the four argparse spellings of each option (``-f KEY``, ``-fKEY``,
    ``--enable-feature KEY``, ``--enable-feature=KEY``, and the ``-F`` /
    ``--disable-feature`` equivalents). Stops at the first token that is not
    one of these options and never looks past a ``--`` separator.
    """
    requested: dict[str, bool] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break
        parsed = _parse_feature_flag_token(token)
        if parsed is None:
            break
        enabled, attached, option_strings = parsed
        if attached is None:
            index += 1
            if index >= len(argv) or argv[index] == "--":
                raise _GlobalOptionError(_missing_value_message(option_strings))
            key = argv[index]
        else:
            key = attached
            if key == "":
                raise _GlobalOptionError(_missing_value_message(option_strings))
        _record_flag_request(requested, key, enabled)
        index += 1
    return dict(requested), list(argv[index:])


def consume_global_options() -> None:
    """Extract leading feature-flag options from ``sys.argv`` and apply them."""
    try:
        values, remaining = _extract_leading_feature_flag_options(sys.argv[1:])
    except _GlobalOptionError as exc:
        _fail_global_option(exc)

    if not values:
        return

    from sase.feature_flags.models import FeatureFlagEnvError
    from sase.feature_flags.registry import feature_flag_definitions
    from sase.feature_flags.snapshot import set_cli_feature_flags

    try:
        definitions = feature_flag_definitions()
        for key in values:
            if key not in definitions:
                raise _GlobalOptionError(
                    f"unknown feature flag {key!r}; see 'sase flag list'"
                )
        set_cli_feature_flags(values)
    except (_GlobalOptionError, FeatureFlagEnvError) as exc:
        _fail_global_option(exc)

    sys.argv[1:] = remaining


def _parse_feature_flag_token(
    token: str,
) -> tuple[bool, str | None, tuple[str, ...]] | None:
    for enabled, option_strings in (
        (True, ENABLE_FEATURE_OPTION_STRINGS),
        (False, DISABLE_FEATURE_OPTION_STRINGS),
    ):
        long_option = _long_option(option_strings)
        short_option = _short_option(option_strings)
        if token in {long_option, short_option}:
            return enabled, None, option_strings
        long_prefix = f"{long_option}="
        if token.startswith(long_prefix):
            return enabled, token[len(long_prefix) :], option_strings
        if (
            token.startswith(short_option)
            and not token.startswith("--")
            and token != short_option
        ):
            return enabled, token[len(short_option) :], option_strings
    return None


def _record_flag_request(requested: dict[str, bool], key: str, enabled: bool) -> None:
    previous = requested.get(key)
    if previous is not None and previous != enabled:
        raise _GlobalOptionError(
            f"feature flag {key!r} cannot be both enabled and disabled"
        )
    requested[key] = enabled


def _long_option(option_strings: Sequence[str]) -> str:
    return next(option for option in option_strings if option.startswith("--"))


def _short_option(option_strings: Sequence[str]) -> str:
    return next(
        option
        for option in option_strings
        if option.startswith("-") and not option.startswith("--")
    )


def _missing_value_message(option_strings: Sequence[str]) -> str:
    return f"argument {'/'.join(option_strings)}: expected one argument"


def _fail_global_option(exc: BaseException) -> NoReturn:
    print(f"sase: error: {exc}", file=sys.stderr)
    sys.exit(2)


__all__ = [
    "FEATURE_FLAG_OPTION_STRINGS",
    "consume_global_options",
    "register_global_feature_flag_options",
]

"""Root-level options parsed from argv before argparse runs."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, NoReturn


ENABLE_FEATURE_OPTION_STRINGS: Final[tuple[str, ...]] = ("-f", "--enable-feature")
DISABLE_FEATURE_OPTION_STRINGS: Final[tuple[str, ...]] = ("-F", "--disable-feature")
FEATURE_FLAG_OPTION_STRINGS: Final[tuple[tuple[str, ...], ...]] = (
    ENABLE_FEATURE_OPTION_STRINGS,
    DISABLE_FEATURE_OPTION_STRINGS,
)
PRINT_COMMAND_OPTION_STRINGS: Final[tuple[str, ...]] = ("-p", "--print-command")

_ENABLE_HELP = "Enable a registered feature flag for this invocation"
_DISABLE_HELP = "Disable a registered feature flag for this invocation"
_PRINT_COMMAND_HELP = "Print the shell-quoted command to stderr before running it"


class _GlobalOptionError(Exception):
    """Raised when a leading root-level option cannot be consumed."""


@dataclass(frozen=True, slots=True)
class _GlobalOptionExtraction:
    """Root option prefix extracted from one argv vector."""

    feature_flags: dict[str, bool]
    print_command: bool
    remaining: list[str]
    display_args: list[str]


@dataclass(frozen=True, slots=True)
class _ShortClusterResult:
    print_command: bool
    display_tokens: list[str]
    next_index: int
    remaining_prefix: list[str]


def register_global_options(parser: argparse.ArgumentParser) -> None:
    """Register root options for help and completion."""
    from sase.completion.kinds import ValueKind, set_completion_kind

    disable = parser.add_argument(
        *DISABLE_FEATURE_OPTION_STRINGS,
        action="append",
        dest="disable_feature",
        metavar="<flag>",
        default=argparse.SUPPRESS,
        help=_DISABLE_HELP,
    )
    enable = parser.add_argument(
        *ENABLE_FEATURE_OPTION_STRINGS,
        action="append",
        dest="enable_feature",
        metavar="<flag>",
        default=argparse.SUPPRESS,
        help=_ENABLE_HELP,
    )
    parser.add_argument(
        *PRINT_COMMAND_OPTION_STRINGS,
        action="store_true",
        dest="print_command",
        default=argparse.SUPPRESS,
        help=_PRINT_COMMAND_HELP,
    )
    set_completion_kind(enable, ValueKind.FLAG)
    set_completion_kind(disable, ValueKind.FLAG)


def _extract_leading_global_options(
    argv: Sequence[str],
) -> _GlobalOptionExtraction:
    """Return leading root options, execution args, and display args.

    ``remaining`` removes every leading root option consumed by SASE before
    dispatch. ``display_args`` removes only the root print option occurrences,
    so the command header still shows behavior-changing feature overrides.
    """
    requested: dict[str, bool] = {}
    print_command = False
    display_args: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break
        if token == "--print-command":
            print_command = True
            index += 1
            continue
        if token.startswith("--print-command="):
            raise _GlobalOptionError(
                _ignored_value_message(PRINT_COMMAND_OPTION_STRINGS, token)
            )

        consumed_feature = _consume_feature_flag_option(argv, index, requested)
        if consumed_feature is not None:
            tokens, index = consumed_feature
            display_args.extend(tokens)
            continue

        consumed_short = _consume_short_option_cluster(argv, index, requested)
        if consumed_short is not None:
            print_command = print_command or consumed_short.print_command
            display_args.extend(consumed_short.display_tokens)
            if consumed_short.remaining_prefix:
                remaining = [
                    *consumed_short.remaining_prefix,
                    *argv[consumed_short.next_index :],
                ]
                return _GlobalOptionExtraction(
                    feature_flags=dict(requested),
                    print_command=print_command,
                    remaining=remaining,
                    display_args=[*display_args, *remaining],
                )
            index = consumed_short.next_index
            continue

        break

    remaining = list(argv[index:])
    return _GlobalOptionExtraction(
        feature_flags=dict(requested),
        print_command=print_command,
        remaining=remaining,
        display_args=[*display_args, *remaining],
    )


def consume_global_options(*, print_command_header: bool = False) -> None:
    """Extract leading root options from ``sys.argv`` and apply them."""
    try:
        extraction = _extract_leading_global_options(sys.argv[1:])
    except _GlobalOptionError as exc:
        _fail_global_option(exc)

    if print_command_header and extraction.print_command:
        from .print_command import write_print_command_header

        write_print_command_header(extraction.display_args)
    _apply_global_options(extraction)
    if not extraction.feature_flags and not extraction.print_command:
        return

    sys.argv[1:] = extraction.remaining


def _apply_global_options(extraction: _GlobalOptionExtraction) -> None:
    """Apply extracted process-affecting root options."""
    _apply_feature_flag_options(extraction.feature_flags)


def _apply_feature_flag_options(values: dict[str, bool]) -> None:
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


def _consume_feature_flag_option(
    argv: Sequence[str],
    index: int,
    requested: dict[str, bool],
) -> tuple[list[str], int] | None:
    token = argv[index]
    parsed = _parse_feature_flag_token(token)
    if parsed is None:
        return None

    enabled, attached, option_strings = parsed
    if attached is None:
        next_index = index + 1
        if next_index >= len(argv) or argv[next_index] == "--":
            raise _GlobalOptionError(_missing_value_message(option_strings))
        key = argv[next_index]
        display_tokens = [token, key]
        next_index += 1
    else:
        key = attached
        if key == "":
            raise _GlobalOptionError(_missing_value_message(option_strings))
        display_tokens = [token]
        next_index = index + 1
    _record_flag_request(requested, key, enabled)
    return display_tokens, next_index


def _consume_short_option_cluster(
    argv: Sequence[str],
    index: int,
    requested: dict[str, bool],
) -> _ShortClusterResult | None:
    token = argv[index]
    if not token.startswith("-") or token.startswith("--") or len(token) < 2:
        return None
    if token[1] != "p":
        return None

    cursor = 1
    print_command = False
    while cursor < len(token):
        flag = token[cursor]
        if flag == "p":
            print_command = True
            cursor += 1
            if cursor < len(token) and token[cursor] == "=":
                raise _GlobalOptionError(
                    _ignored_value_message(
                        PRINT_COMMAND_OPTION_STRINGS,
                        token,
                        value=token[cursor + 1 :],
                    )
                )
            continue

        if flag in {"f", "F"}:
            enabled = flag == "f"
            option = f"-{flag}"
            attached = token[cursor + 1 :]
            if attached:
                key = attached
                display_tokens = [f"{option}{attached}"]
                next_index = index + 1
            else:
                next_index = index + 1
                if next_index >= len(argv) or argv[next_index] == "--":
                    option_strings = (
                        ENABLE_FEATURE_OPTION_STRINGS
                        if enabled
                        else DISABLE_FEATURE_OPTION_STRINGS
                    )
                    raise _GlobalOptionError(_missing_value_message(option_strings))
                key = argv[next_index]
                display_tokens = [option, key]
                next_index += 1
            _record_flag_request(requested, key, enabled)
            return _ShortClusterResult(
                print_command=print_command,
                display_tokens=display_tokens,
                next_index=next_index,
                remaining_prefix=[],
            )

        if flag == "-":
            raise _GlobalOptionError(
                _ignored_value_message(
                    PRINT_COMMAND_OPTION_STRINGS,
                    token,
                    value=token[cursor:],
                )
            )

        return _ShortClusterResult(
            print_command=print_command,
            display_tokens=[],
            next_index=index + 1,
            remaining_prefix=[f"-{token[cursor:]}"],
        )

    return _ShortClusterResult(
        print_command=print_command,
        display_tokens=[],
        next_index=index + 1,
        remaining_prefix=[],
    )


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


def _ignored_value_message(
    option_strings: Sequence[str], token: str, *, value: str | None = None
) -> str:
    explicit_value = token.split("=", 1)[1] if value is None and "=" in token else value
    if explicit_value is None:
        explicit_value = token[2:]
    return (
        f"argument {'/'.join(option_strings)}: "
        f"ignored explicit argument {explicit_value!r}"
    )


def _fail_global_option(exc: BaseException) -> NoReturn:
    print(f"sase: error: {exc}", file=sys.stderr)
    sys.exit(2)


__all__ = [
    "FEATURE_FLAG_OPTION_STRINGS",
    "PRINT_COMMAND_OPTION_STRINGS",
    "consume_global_options",
    "register_global_options",
]

"""Low-overhead CLI hit capture for Footprint."""

from __future__ import annotations

import argparse
from datetime import date
import os
import sys
import time
from collections.abc import Iterable, Sequence
from typing import Any

from sase.footprint import ids
from sase.footprint._mode import current_mode

_ACTIVE_HIT: CliHit | None = None
_AGENT = "agent"
_AUTOMATION = "automation"
_HUMAN = "human"
_UNKNOWN = "unknown"


class CliHit:
    """One in-memory CLI hit, written at most once from the entry finally."""

    def __init__(self, mode: str, started_ns: int, day: str, actor: str, via: str):
        self.mode = mode
        self.started_ns = started_ns
        self.day = day
        self.actor = actor
        self.via = via
        self.feature = ids.ROOT_COMMAND_ID
        self.options: list[str] = []
        self._parse_stage = False
        self._help_requested = False
        self._recorded = False

    def set_path(self, words: Sequence[str]) -> None:
        """Set a command path made only from parser or fast-path command words."""
        if not self.active:
            return
        normalized = [ids.CLI_ALIASES.get(word, word) for word in words]
        self.feature = ids.cli_id(normalized)

    def set_feature(self, feature_id: str) -> None:
        """Set a prevalidated feature ID for non-argparse dispatch."""
        if self.active and ids.is_valid_feature_id(feature_id):
            self.feature = feature_id

    def set_plugin(self, word: str) -> None:
        """Record a first-party plugin or collapse all custom names."""
        if word in ids.FIRST_PARTY_PLUGIN_COMMANDS:
            self.set_feature(f"plugin:{word}")
        else:
            self.set_feature("plugin:~third_party")

    def set_options(self, dests: Iterable[str]) -> None:
        """Set parser option destinations, never option values."""
        if not self.active:
            return
        unique: list[str] = []
        for dest in dests:
            if not isinstance(dest, str) or not dest or dest == argparse.SUPPRESS:
                continue
            safe = ids.sanitize(dest)
            if safe and safe not in unique:
                unique.append(safe)
            if len(unique) == 16:
                break
        self.options = unique
        self._help_requested = any(dest in {"help", "full_help"} for dest in unique)

    def mark_parse_stage(self) -> None:
        """Mark that argparse owns this invocation's outcome classification."""
        self._parse_stage = True

    @property
    def active(self) -> bool:
        return self.mode in {"local", "test"} and not self._recorded

    def record(self, outcome: int | BaseException | None = 0) -> None:
        """Append one record and swallow failures so CLI behavior is unchanged."""
        if self._recorded:
            return
        self._recorded = True
        if self.mode not in {"local", "test"}:
            return
        try:
            from sase.footprint._spool import append_lines

            line = self._line(self._outcome(outcome))
            append_lines((line,), mode=self.mode, day=self.day)
        except BaseException:
            return

    def _line(self, outcome: str) -> str:
        options = self.options[:16]
        while True:
            option_field = ""
            if options:
                option_field = (
                    ',"opt":[' + ",".join(f'"{item}"' for item in options) + "]"
                )
            elapsed_ms = max(0, (time.perf_counter_ns() - self.started_ns) // 1_000_000)
            line = (
                f'{{"s":1,"d":"{self.day}","f":"{self.feature}",'
                f'"a":"{self.actor}","v":"{self.via}","o":"{outcome}",'
                f'"n":1,"ms":{elapsed_ms}{option_field},"ver":"{_version()}"}}'
            )
            if len(line.encode("ascii")) + 1 <= 512 or not options:
                return line
            options.pop()

    def _outcome(self, result: int | BaseException | None) -> str:
        if isinstance(result, BaseException):
            if isinstance(result, KeyboardInterrupt):
                return "cancelled"
            if isinstance(result, SystemExit):
                code = result.code
                if code is None or code == 0:
                    return "help" if self._help_requested else "ok"
                if code == 130:
                    return "cancelled"
                if code == 2 and self._parse_stage:
                    return "usage_error"
                return "error"
            return "error"
        if result is None or result == 0:
            return "help" if self._help_requested else "ok"
        if result == 130:
            return "cancelled"
        if result == 2 and self._parse_stage:
            return "usage_error"
        return "error"


def begin() -> CliHit:
    """Begin a process hit, checking the mode before actor or parser work."""
    mode = current_mode()
    actor = _UNKNOWN
    via = "cli"
    if mode in {"local", "test"}:
        from sase.footprint._actor import classify_actor

        actor, via = classify_actor()
    hit = CliHit(mode, time.perf_counter_ns(), date.today().isoformat(), actor, via)
    global _ACTIVE_HIT
    _ACTIVE_HIT = hit
    return hit


def record_active(outcome: int | BaseException | None = 0) -> None:
    """Record before an ``os._exit`` or ``os.execv`` bypasses ``finally``."""
    hit = _ACTIVE_HIT
    if hit is not None:
        hit.record(outcome)


def disable_active() -> None:
    """Prevent the current process from appending after `mode off` is set."""
    hit = _ACTIVE_HIT
    if hit is not None:
        hit.mode = "off"


def set_parser_path(
    hit: CliHit, parser: argparse.ArgumentParser, argv: Sequence[str]
) -> None:
    """Resolve the safe parser command path and its leaf option destinations."""
    feature_id, dests = resolve_command_ids(parser, argv)
    hit.set_feature(feature_id)
    hit.set_options(dests)


def resolve_command_ids(
    parser: argparse.ArgumentParser, argv: Sequence[str]
) -> tuple[str, list[str]]:
    """Return ``(feature_id, option dests)`` for *argv* after the ``sase`` word.

    First-party plugin command words are recorded as ``plugin:<word>``.
    Everything else walks the parser the same way the live CLI recorder does.
    """
    if argv and argv[0] in ids.FIRST_PARTY_PLUGIN_COMMANDS:
        return f"plugin:{argv[0]}", []
    words, leaf = _parser_path(parser, argv)
    return ids.cli_id(words), _option_dests(leaf, argv)


def _parser_path(
    parser: argparse.ArgumentParser, argv: Sequence[str]
) -> tuple[list[str], argparse.ArgumentParser]:
    """Walk only subparser choices, skipping option values and all positionals."""
    current = parser
    words: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break
        if token.startswith("-") and token != "-":
            option = token.partition("=")[0]
            action = current._option_string_actions.get(option)
            index += 1 + _option_value_count(action, token, argv, index)
            continue
        subparsers = _subparser_action(current)
        if subparsers is None:
            index += 1
            continue
        child = subparsers.choices.get(token)
        if child is None:
            if not words:
                return ["~other"], current
            break
        words.append(ids.CLI_ALIASES.get(token, token))
        current = child
        index += 1
    return words, current


def _option_dests(parser: argparse.ArgumentParser, argv: Sequence[str]) -> list[str]:
    """Resolve recognized option strings through the leaf parser only."""
    dests: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break
        if not token.startswith("-") or token == "-":
            index += 1
            continue
        option = token.partition("=")[0]
        action = parser._option_string_actions.get(option)
        if action is None:
            index += 1
            continue
        if isinstance(action.dest, str) and action.dest != argparse.SUPPRESS:
            dests.append(action.dest)
        index += 1 + _option_value_count(action, token, argv, index)
    return dests


def _subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction[Any] | None:
    return next(
        (
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ),
        None,
    )


def _option_value_count(
    action: argparse.Action | None,
    token: str,
    argv: Sequence[str],
    index: int,
) -> int:
    if action is None or "=" in token or action.nargs == 0:
        return 0
    nargs = action.nargs
    if nargs is None:
        return 1 if index + 1 < len(argv) else 0
    if isinstance(nargs, int):
        return min(nargs, max(0, len(argv) - index - 1))
    if nargs == "?":
        return int(index + 1 < len(argv) and not argv[index + 1].startswith("-"))
    if nargs in {"*", "+"}:
        count = 0
        cursor = index + 1
        while (
            cursor < len(argv)
            and argv[cursor] != "--"
            and not argv[cursor].startswith("-")
        ):
            count += 1
            cursor += 1
        return count
    return 0


def _version() -> str:
    from sase import __version__

    return __version__


__all__ = [
    "CliHit",
    "begin",
    "disable_active",
    "record_active",
    "resolve_command_ids",
    "set_parser_path",
]

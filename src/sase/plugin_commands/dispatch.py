"""Pre-argparse dispatch fast path for plugin-mounted top-level commands.

Runs only for root words that are not built-in commands: built-in dispatch
pays one dict lookup and never imports ``importlib.metadata`` through this
path. On no match this returns ``None`` so entry falls through untouched and
the full-parser fallback output stays byte-identical.

Only stdlib imports live at module top; the scan, registry, adapter, hints,
and chip helpers load lazily inside :func:`try_handle_plugin_command`, after
the built-in check has passed.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.plugin_commands.scan import PluginCommandRecord


def try_handle_plugin_command(argv: Sequence[str]) -> int | None:
    """Dispatch ``sase <plugin-command>`` or return ``None`` to fall through.

    Global options are already consumed before the command word, so everything
    after it — including ``-h``, ``--``, and same-spelled flags — belongs to
    the plugin. Load failures and conflicts exit 1; helpful misses exit 2.
    ``SystemExit`` raised by the plugin's own ``main`` propagates unchanged,
    and exceptions from ``main`` are never caught here.
    """
    from sase.main.parser_registry import _COMMAND_REGISTRARS
    from sase.main.parser_root_args import root_command_index

    index = root_command_index(argv)
    if index is None:
        return None
    word = argv[index]
    if not isinstance(word, str) or word.startswith("-") or word in _COMMAND_REGISTRARS:
        return None

    from sase.plugin_commands.registry import discover_plugin_commands

    command_set = discover_plugin_commands()
    mounted = command_set.mounted_by_name()
    record = mounted.get(word)
    if record is not None:
        return _run_mounted_command(word, list(argv[index + 1 :]), record)

    problem = command_set.problem_by_name(word)
    if problem is not None and problem.status == "conflict":
        return _report_conflict(word, problem.distributions)
    if problem is not None:
        # Shadowed (reserved) and invalid names stay on the argparse path so
        # the existing unknown-command error remains authoritative.
        return None

    from sase.plugin_commands.hints import maybe_handle_plugin_hint

    return maybe_handle_plugin_hint(word)


def _run_mounted_command(
    word: str, rest: list[str], record: PluginCommandRecord
) -> int:
    from sase.plugin_commands.adapter import PluginCommandLoadError, load_plugin_command

    try:
        loaded = load_plugin_command(record)
    except PluginCommandLoadError as exc:
        print(
            f"sase: the '{word}' command from {exc.distribution} "
            f"{exc.version} failed to load: {exc.cause}",
            file=sys.stderr,
        )
        print(f"sase plugin update {word}", file=sys.stderr)
        return 1
    prog = f"sase {word}"
    sys.argv = [prog, *rest]
    result = loaded.main(list(rest), prog=prog)
    if result is None:
        return 0
    return int(result)


def _report_conflict(word: str, distributions: tuple[str, ...]) -> int:
    from sase.plugin_commands.chip import format_command_chip

    owners = ", ".join(distributions)
    print(
        f"sase: {format_command_chip(word)} is disabled:"
        f" claimed by more than one plugin ({owners}).",
        file=sys.stderr,
    )
    print(
        f"Uninstall one of them: sase plugin uninstall {distributions[0]}",
        file=sys.stderr,
    )
    return 1

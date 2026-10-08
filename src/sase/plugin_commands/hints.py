"""Helpful misses for words that are neither built-in nor mounted commands.

Uses only the offline catalog cache, so misses never make a network call.
Rich is used only when stderr supports color; otherwise plain text is printed
and rich is never imported.
"""

from __future__ import annotations

import importlib.metadata
import sys
from typing import Any


def maybe_handle_plugin_hint(word: str) -> int | None:
    """Print a plugin hint for *word* and return its exit code, if any.

    Returns ``2`` when a hint applied (disabled switch, installed-but-too-old
    distribution, or catalogued-but-not-installed plugin), or ``None`` to fall
    through to the existing argparse error unchanged.
    """
    from sase.plugin_commands.scan import (
        commands_disabled,
        disabling_env_var,
        scan_plugin_commands,
    )

    claimed = {record.name for record in scan_plugin_commands(honor_disable=False)}
    if word in claimed and commands_disabled():
        _print_hint(
            f"sase: the '{word}' command is disabled "
            f"by {disabling_env_var()} (unset it to enable plugin commands)."
        )
        return 2
    too_old = _installed_without_entry_point(word)
    if too_old is not None:
        distribution, version = too_old
        _print_hint(
            f"{distribution} {version} is installed but predates "
            f"'sase {word}' — run sase plugin update {word}"
        )
        return 2
    catalogued = _catalogued_not_installed(word, claimed)
    if catalogued is not None:
        plugin_name, full_name = catalogued
        _print_hint(
            f"sase: '{word}' is provided by the {plugin_name} plugin ({full_name}).\n"
            f"Install it: sase plugin install {plugin_name}   "
            "(or the Updates tab in sase's Admin Center)"
        )
        return 2
    return None


def _installed_without_entry_point(word: str) -> tuple[str, str] | None:
    """Return ``(distribution, version)`` when an installed dist predates the command."""
    from sase.plugin_commands.scan import COMMANDS_ENTRY_POINT_GROUP

    for candidate in (f"sase-{word}", word):
        try:
            dist = importlib.metadata.distribution(candidate)
        except importlib.metadata.PackageNotFoundError:
            continue
        except Exception:
            continue
        try:
            declared = [
                ep for ep in dist.entry_points if ep.group == COMMANDS_ENTRY_POINT_GROUP
            ]
        except Exception:
            continue
        if not declared:
            raw_name = dist.metadata.get("Name", candidate)
            name: str = (
                raw_name if isinstance(raw_name, str) and raw_name else candidate
            )
            raw_version = dist.version
            version: str = (
                raw_version
                if isinstance(raw_version, str) and raw_version
                else "<unknown>"
            )
            return (name, version)
        return None
    return None


def _catalogued_not_installed(word: str, claimed: set[str]) -> tuple[str, str] | None:
    """Return ``(plugin_name, full_name)`` for a catalogued but uninstalled plugin."""
    if word in claimed:
        return None
    entries = _read_catalog_entries()
    for entry in entries:
        raw_name = entry.get("name")
        name: str = raw_name if isinstance(raw_name, str) else ""
        raw_repo = entry.get("repo")
        repo: str = raw_repo if isinstance(raw_repo, str) else ""
        raw_full_name = entry.get("full_name")
        full_name: str = raw_full_name if isinstance(raw_full_name, str) else ""
        if not full_name:
            continue
        if word and (word == name or word == repo or repo == f"sase-{word}"):
            return (name or repo, full_name)
    return None


def _read_catalog_entries() -> tuple[dict[str, Any], ...]:
    try:
        from sase.plugins.cache import read_cache
    except Exception:
        return ()
    try:
        cached = read_cache()
    except Exception:
        return ()
    if cached is None:
        return ()
    return cached.entries


def _print_hint(message: str) -> None:
    from sase.core.term_color import should_colorize

    if should_colorize(sys.stderr):
        from rich.console import Console

        console = Console(file=sys.stderr, force_terminal=True, highlight=False)
        console.print(message, style="yellow")
        return
    sys.stderr.write(message + "\n")

"""Pre-argparse fast paths for latency-sensitive ``sase completion`` commands.

Mirrors ``bead_fast_path.py``: a hand-rolled ``str``-comparison parser, no
``argparse``, no ``sase.config``, no ``rich``, called from ``entry.py`` before
``from .parser import ...``. This keeps live values and runtime grammar
resolution from paying for a full argparse tree build in shell-completion
hot paths.
"""

from __future__ import annotations

import sys

_HELP_FLAGS = frozenset({"-h", "--help"})
_LIMIT_FLAGS = frozenset({"-l", "--limit"})
_ENSURE_FORCE_FLAGS = frozenset({"-f", "--force"})
_ENSURE_LOADER_PATH_FLAGS = frozenset({"-p", "--loader-path"})
_ENSURE_OWNER_FLAGS = frozenset({"-O", "--owner"})
_ENSURE_TARGET_FLAGS = frozenset({"-t", "--target"})
_PROJECT_FLAGS = frozenset({"-p", "--project"})
_SUPPORTED_SHELLS = frozenset({"bash", "fish", "zsh"})


def try_handle_completion_candidates(argv: list[str]) -> int | None:
    """Handle ``sase completion candidates <KIND> [PREFIX] ...``.

    Returns an exit code when handled, or ``None`` when argparse should
    handle the command instead -- covering ``-h``/``--help`` and any argv
    shape this hand-rolled parser does not recognize, so the normal parser's
    help text and error messages stay authoritative for those cases.
    """
    if not argv or any(arg in _HELP_FLAGS for arg in argv):
        return None

    parsed = _parse_argv(argv)
    if parsed is None:
        return None
    kind, prefix, project, limit = parsed

    from sase.completion.candidates.protocol import render_candidates
    from sase.completion.candidates.providers import candidates_for

    output = render_candidates(
        candidates_for(kind, prefix, project=project, limit=limit)
    )
    if output:
        sys.stdout.write(output)
        sys.stdout.write("\n")
    return 0


def try_handle_completion_ensure(argv: list[str]) -> int | None:
    """Handle ``sase completion ensure SHELL`` without importing argparse."""
    if not argv or any(arg in _HELP_FLAGS for arg in argv):
        return None

    parsed = _parse_ensure_argv(argv)
    if parsed is None:
        return None
    shell, force, loader_path, owner, target = parsed

    from sase.completion.runtime_cache import (
        CompletionCacheError,
        ensure_cached_grammar,
    )

    try:
        path = ensure_cached_grammar(
            shell,
            force=force,
            loader_path=loader_path,
            owner=owner,
            target=target,
        )
    except CompletionCacheError as exc:
        print(f"sase completion ensure: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(str(path))
    sys.stdout.write("\n")
    return 0


def _parse_argv(argv: list[str]) -> tuple[str, str, str | None, int] | None:
    """Parse ``candidates`` argv, or ``None`` for any shape argparse should own."""
    from sase.completion.candidates.protocol import DEFAULT_LIMIT

    positionals: list[str] = []
    project: str | None = None
    limit = DEFAULT_LIMIT

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in _LIMIT_FLAGS:
            value, index = _take_value(argv, index)
            if value is None or not value.isdigit():
                return None
            limit = int(value)
        elif arg.startswith("--limit="):
            value = arg[len("--limit=") :]
            if not value.isdigit():
                return None
            limit = int(value)
            index += 1
        elif arg in _PROJECT_FLAGS:
            value, index = _take_value(argv, index)
            if value is None:
                return None
            project = value
        elif arg.startswith("--project="):
            project = arg[len("--project=") :]
            index += 1
        elif arg.startswith("-") and arg not in {"-", "--"}:
            # An unrecognized flag: defer so argparse reports it properly.
            return None
        else:
            positionals.append(arg)
            index += 1

    if not positionals or len(positionals) > 2:
        return None
    kind = positionals[0]
    prefix = positionals[1] if len(positionals) == 2 else ""
    return kind, prefix, project, limit


def _parse_ensure_argv(
    argv: list[str],
) -> tuple[str, bool, str | None, str | None, str | None] | None:
    positionals: list[str] = []
    force = False
    loader_path: str | None = None
    owner: str | None = None
    target: str | None = None

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in _ENSURE_FORCE_FLAGS:
            force = True
            index += 1
        elif arg in _ENSURE_LOADER_PATH_FLAGS:
            loader_path, index = _take_value(argv, index)
            if loader_path is None:
                return None
        elif arg.startswith("--loader-path="):
            loader_path = arg[len("--loader-path=") :]
            index += 1
        elif arg in _ENSURE_OWNER_FLAGS:
            owner, index = _take_value(argv, index)
            if owner is None:
                return None
        elif arg.startswith("--owner="):
            owner = arg[len("--owner=") :]
            index += 1
        elif arg in _ENSURE_TARGET_FLAGS:
            target, index = _take_value(argv, index)
            if target is None:
                return None
        elif arg.startswith("--target="):
            target = arg[len("--target=") :]
            index += 1
        elif arg.startswith("-") and arg not in {"-", "--"}:
            return None
        else:
            positionals.append(arg)
            index += 1

    if len(positionals) != 1:
        return None
    shell = positionals[0]
    if shell not in _SUPPORTED_SHELLS:
        return None
    if owner is not None and owner not in {"chezmoi", "local"}:
        return None
    if loader_path is not None and target is not None:
        return None
    return shell, force, loader_path, owner, target


def _take_value(argv: list[str], index: int) -> tuple[str | None, int]:
    if index + 1 >= len(argv):
        return None, index + 1
    return argv[index + 1], index + 2


__all__ = ["try_handle_completion_candidates", "try_handle_completion_ensure"]

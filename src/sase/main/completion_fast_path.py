"""Pre-argparse fast path for ``sase completion candidates``.

Mirrors ``bead_fast_path.py``: a hand-rolled ``str``-comparison parser, no
``argparse``, no ``sase.config``, no ``rich``, called from ``entry.py`` before
``from .parser import ...``. This is the door that makes live completion
values possible without paying for a full argparse tree build on every
keystroke.
"""

from __future__ import annotations

import sys

_HELP_FLAGS = frozenset({"-h", "--help"})
_LIMIT_FLAGS = frozenset({"-l", "--limit"})
_PROJECT_FLAGS = frozenset({"-p", "--project"})


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


def _take_value(argv: list[str], index: int) -> tuple[str | None, int]:
    if index + 1 >= len(argv):
        return None, index + 1
    return argv[index + 1], index + 2


__all__ = ["try_handle_completion_candidates"]

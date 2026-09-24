"""Command-line proc tag and submission contract.

Finished procs tagged ``command-line`` (submitted from the TUI Command Line)
keep their own retention bucket so heavy Command Line use never evicts
operational proc history. The Rust store owns the bucket; the values here
mirror ``sase_core::procs`` (see the ``command_line_proc_tag`` and
``command_line_proc_history_limit`` bindings) the way
``sase.procs.models`` mirrors the proc wire schema version.

This module is TUI-independent so another frontend can reuse the submission
contract: it builds the canonical ``python -m sase …`` argv inline (the same
shape as :func:`sase.ace.tui.durable_ops.sase_command_argv`, which cannot be
imported here without a ``procs -> ace`` layering cycle) instead of reaching
into ACE.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .models import Proc
from .request import ProcSubmitRequest
from .submission import submit_proc_request

#: Tag carried by procs submitted from the TUI Command Line.
COMMAND_LINE_PROC_TAG: Final = "command-line"
#: Finished procs carrying the tag kept beside the generic history bucket.
COMMAND_LINE_PROC_HISTORY_LIMIT: Final = 50

#: Output environment every command-line proc runs with.
COMMAND_LINE_PROC_ENV: Final = {
    "PYTHONUNBUFFERED": "1",
    "FORCE_COLOR": "1",
}


def submit_command_line_proc(
    argv_tokens: Sequence[str],
    *,
    cwd: str | Path,
    project: str | None,
    width: int,
    session_id: str | None = None,
) -> Proc:
    """Submit TUI Command Line tokens as a tagged ordinary proc.

    The proc carries the ``command-line`` tag with ``origin="ace"``, the
    output env contract (unbuffered, forced color, ``COLUMNS`` from the
    transcript width), and no operation, service block, or concurrency keys.
    """
    tokens = [str(part) for part in argv_tokens]
    request = ProcSubmitRequest(
        argv=[sys.executable, "-m", "sase", *tokens],
        command=["sase", *tokens],
        label=": " + shlex.join(tokens),
        cwd=cwd,
        origin="ace",
        tags=(COMMAND_LINE_PROC_TAG,),
        env={**COMMAND_LINE_PROC_ENV, "COLUMNS": str(int(width))},
        project=project,
        session_id=session_id,
    )
    return submit_proc_request(request)


__all__ = [
    "COMMAND_LINE_PROC_ENV",
    "COMMAND_LINE_PROC_HISTORY_LIMIT",
    "COMMAND_LINE_PROC_TAG",
    "submit_command_line_proc",
]

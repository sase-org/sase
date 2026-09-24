"""Command-line proc tag and retention bucket.

Finished procs tagged ``command-line`` (submitted from the TUI Command Line)
keep their own retention bucket so heavy Command Line use never evicts
operational proc history. The Rust store owns the bucket; the values here
mirror ``sase_core::procs`` (see the ``command_line_proc_tag`` and
``command_line_proc_history_limit`` bindings) the way
``sase.procs.models`` mirrors the proc wire schema version.
"""

from __future__ import annotations

from typing import Final

#: Tag carried by procs submitted from the TUI Command Line.
COMMAND_LINE_PROC_TAG: Final = "command-line"
#: Finished procs carrying the tag kept beside the generic history bucket.
COMMAND_LINE_PROC_HISTORY_LIMIT: Final = 50

__all__ = [
    "COMMAND_LINE_PROC_HISTORY_LIMIT",
    "COMMAND_LINE_PROC_TAG",
]

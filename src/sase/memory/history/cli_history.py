"""``sase memory history`` command: timelines, versions, diffs, and the feed.

With no selector the command shows the cross-file changes feed; with
one or more selectors it shows each subject's timeline. ``-A`` selects
one version (with its body), ``-d`` shows the change instead of the
body, and ``-f json`` emits the Rust wire unchanged for agents.

The command never writes a read-audit event: viewing history is not an
audited read (epic design ``plan:202609/memory_history.md`` D10).

This module is a facade preserving the original public import path.
Command logic lives in :mod:`sase.memory.history.cli_history_command`;
selector translation lives in
:mod:`sase.memory.history.cli_history_selectors`.
"""

from __future__ import annotations

from sase.memory.history.cli_history_command import (
    handle_memory_history_command as handle_memory_history_command,
)
from sase.memory.history.cli_history_selectors import (
    translate_history_selector as translate_history_selector,
)

__all__ = ["handle_memory_history_command"]

"""ACE ChangeSpec read provider helpers."""

from __future__ import annotations

from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.daemon.changespec_reads import read_changespecs_or_fallback
from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult


def read_changespecs_for_tui(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[list[ChangeSpec]]:
    """Return the ACE ChangeSpec snapshot through daemon reads when possible."""

    from ....changespec import find_all_changespecs_cached

    return read_changespecs_or_fallback(
        "changespec_list",
        args=args,
        client=client,
        direct_loader=find_all_changespecs_cached,
    )


__all__ = ["read_changespecs_for_tui"]

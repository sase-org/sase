"""Helpers for fakes that stand in for ACE proc submitters."""

from __future__ import annotations

import inspect
from typing import Any

from sase.ace.tui.actions.proc_actions import ProcActionsMixin


def assert_session_worker_submit_signature(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    """Fail if a fake session submitter receives kwargs the real method rejects."""
    inspect.signature(ProcActionsMixin._submit_session_worker).bind_partial(
        None,
        *args,
        **kwargs,
    )

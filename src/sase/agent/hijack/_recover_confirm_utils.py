"""Shared private helpers for recovery confirmation modules."""

from __future__ import annotations

import os
from typing import Any

from sase.agent.hijack.recover_common import clean_string


def same_path(left: Any, right: Any) -> bool:
    left_value = clean_string(left)
    right_value = clean_string(right)
    return bool(
        left_value
        and right_value
        and os.path.normcase(os.path.normpath(left_value))
        == os.path.normcase(os.path.normpath(right_value))
    )


def process_identity_token(pid: int) -> str | None:
    from sase.core.process_identity import process_identity_token as read_token

    try:
        return read_token(int(pid)) or None
    except Exception:
        return None

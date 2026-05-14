"""Helpers shared by daemon lifecycle compatibility facade modules."""

from __future__ import annotations

import sys
from typing import Any


def lifecycle_facade() -> Any:
    return sys.modules["sase.integrations.daemon_lifecycle"]

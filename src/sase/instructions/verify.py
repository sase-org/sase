"""Collect instruction observations and build verification reports."""

from __future__ import annotations

from sase.instructions._verify_aggregate import build_report
from sase.instructions._verify_collection import collect_observations

__all__ = ["build_report", "collect_observations"]

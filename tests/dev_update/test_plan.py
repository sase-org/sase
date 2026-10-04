"""Tests for dev-update root planning.

Split into focused modules; this facade preserves the original test import path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.dev_update.plan import plan_dev_update
import sase.dev_update._plan_roots as plan_mod
from sase.uv_tool.receipt import parse_receipt
from sase.version._git import GitUpstreamStatus
from tests.dev_update._plan_helpers import probe, record, status
from tests.dev_update.test_plan_actionability import (
    test_plan_dev_update_receipt_absence_is_explicit,
    test_plan_dev_update_skips_non_actionable_roots,
    test_plan_dev_update_unknown_source_root_skips_without_gitprobe,
)
from tests.dev_update.test_plan_fetch import (
    test_plan_dev_update_does_not_fetch_no_upstream_or_detached_roots,
    test_plan_dev_update_fetch_failure_degrades_honestly,
    test_plan_dev_update_fetches_before_classifying_root_actionability,
    test_plan_dev_update_fetches_once_per_root,
    test_plan_dev_update_reuses_only_explicitly_refreshed_roots,
)

__test__ = False

__all__ = [
    "GitUpstreamStatus",
    "Path",
    "parse_receipt",
    "plan_dev_update",
    "plan_mod",
    "probe",
    "pytest",
    "record",
    "status",
    "subprocess",
    "test_plan_dev_update_does_not_fetch_no_upstream_or_detached_roots",
    "test_plan_dev_update_fetch_failure_degrades_honestly",
    "test_plan_dev_update_fetches_before_classifying_root_actionability",
    "test_plan_dev_update_fetches_once_per_root",
    "test_plan_dev_update_receipt_absence_is_explicit",
    "test_plan_dev_update_reuses_only_explicitly_refreshed_roots",
    "test_plan_dev_update_skips_non_actionable_roots",
    "test_plan_dev_update_unknown_source_root_skips_without_gitprobe",
]

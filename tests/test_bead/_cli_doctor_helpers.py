"""Shared helpers for bead doctor CLI tests.

Split from ``tests.test_bead.test_cli_doctor``; the original module
re-exports its tests so its import path keeps working.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_cli_doctor_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import argparse


def doctor_args(**overrides: bool) -> argparse.Namespace:
    """Build a bead-doctor namespace with test-friendly defaults."""
    defaults = {
        "fix_design_refs": False,
        "fix_issue_prefix": False,
        "fix_plan_archive": False,
        "fix_projection": False,
        "verify_cache": False,
        "yes": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)

"""Reject the retired pytest golden-write option with a replacement command."""

from __future__ import annotations

import pytest

LEGACY_VISUAL_UPDATE_OPTION = "--sase-update-visual-snapshots"
LEGACY_VISUAL_UPDATE_REMEDIATION = (
    "--sase-update-visual-snapshots is retired. "
    "Run `just fix-tui-screenshots` to capture, compare, and apply screenshot "
    "goldens, or `just fix-tui-screenshots --check` to inventory without writing. "
    "Targeted selectors go after `--`, for example "
    "`just fix-tui-screenshots -- tests/ace/tui/visual/test_example.py -k example`."
)


def reject_legacy_visual_update_option(config: pytest.Config) -> None:
    """Refuse fixture-driven golden writes via the retired pytest flag."""
    if config.getoption(LEGACY_VISUAL_UPDATE_OPTION, default=False):
        raise pytest.UsageError(LEGACY_VISUAL_UPDATE_REMEDIATION)

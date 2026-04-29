"""Golden tests pinning the line-based STATUS helpers used by the wire.

The Phase 4B contract guarantees that
:func:`sase.core.status_facade.read_status_from_lines` and
:func:`sase.core.status_facade.apply_status_update` produce the exact
strings exercised here. The Phase 4C Rust implementations must match.
"""

from __future__ import annotations

import pytest

from sase.core.status_facade import apply_status_update, read_status_from_lines

pytestmark = pytest.mark.usefixtures("python_core_backend")


_PROJECT_LINES = [
    "## ChangeSpec\n",
    "\n",
    "NAME: alpha\n",
    "DESCRIPTION:\n",
    "  alpha desc\n",
    "STATUS: Ready\n",
    "\n",
    "---\n",
    "\n",
    "## ChangeSpec\n",
    "\n",
    "NAME: beta\n",
    "DESCRIPTION:\n",
    "  beta desc\n",
    "STATUS: Draft\n",
    "\n",
    "---\n",
]


def test_read_status_from_lines_matches_first_changespec() -> None:
    assert read_status_from_lines(_PROJECT_LINES, "alpha") == "Ready"


def test_read_status_from_lines_matches_second_changespec() -> None:
    assert read_status_from_lines(_PROJECT_LINES, "beta") == "Draft"


def test_read_status_from_lines_returns_none_when_missing() -> None:
    assert read_status_from_lines(_PROJECT_LINES, "gamma") is None


def test_read_status_preserves_workspace_suffix() -> None:
    lines = [
        "NAME: thing\n",
        "STATUS: Ready (proj_2)\n",
    ]
    assert read_status_from_lines(lines, "thing") == "Ready (proj_2)"


def test_apply_status_update_replaces_only_target_status() -> None:
    updated = apply_status_update(_PROJECT_LINES, "alpha", "Mailed")
    assert "STATUS: Mailed\n" in updated
    # The other ChangeSpec's STATUS must be untouched.
    assert "STATUS: Draft\n" in updated
    # The replaced original must be gone.
    assert "STATUS: Ready\n" not in updated


def test_apply_status_update_preserves_unrelated_lines() -> None:
    """Non-STATUS lines pass through verbatim including blank lines / separators."""
    updated = apply_status_update(_PROJECT_LINES, "alpha", "Mailed")
    # Check each non-STATUS line of the alpha block survived.
    assert "NAME: alpha\n" in updated
    assert "  alpha desc\n" in updated
    assert "---\n" in updated


def test_apply_status_update_no_matching_changespec_is_noop() -> None:
    updated = apply_status_update(_PROJECT_LINES, "gamma", "Mailed")
    assert updated == "".join(_PROJECT_LINES)


def test_apply_status_update_idempotent_when_status_already_matches() -> None:
    updated = apply_status_update(_PROJECT_LINES, "beta", "Draft")
    assert updated == "".join(_PROJECT_LINES)

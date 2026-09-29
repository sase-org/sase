"""Shared builders for direct-approval recovery tests.

Split from ``tests.test_plan_direct_approval_recovery``; the original module
re-exports its tests so its import path keeps working.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_plan_direct_approval_recovery_*`` split modules can
share them without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.plan_direct_approval_recovery import PriorCoder
from sase.main.plan_pending_diagnosis import PlanGateHistory
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture(autouse=True)
def no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable color for recovery assertions.

    Importing this fixture's name into a test module is enough for pytest to
    pick it up, since fixture discovery scans the module's own namespace.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)


@pytest.fixture(name="sase_home_dir")
def recovery_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SASE home to a temporary directory."""
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    monkeypatch.chdir(tmp_path)
    return home


def local_plan(home: Path, name: str = "work.md") -> Path:
    """Write a valid tale plan under a redirected SASE home."""
    plan = home / "plans" / "202609" / name
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    return plan


def handled_history(**overrides: object) -> PlanGateHistory:
    """Build a handled gate history for recovery evaluation."""
    fields: dict[str, object] = {
        "kind": "handled",
        "action": "approve",
        "age": " (7m ago)",
        "notification_id": "gate123",
        "bundle_path": Path("/tmp/gate-bundle"),
        "action_data": {"agent_name": "0sk"},
    }
    fields.update(overrides)
    return PlanGateHistory(**fields)  # type: ignore[arg-type]


def failed_prior(name: str = "0sk--code") -> PriorCoder:
    """Build a failed prior coder for recovery evaluation."""
    return PriorCoder(name=name, state="ended", outcome="failed", age="14m ago")

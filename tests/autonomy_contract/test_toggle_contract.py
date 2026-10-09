"""Toggle contract: ``A`` off then on restores the last profile.

For a ``%auto:tale`` agent, ``A`` off then on gives the tale outcomes
through core ``mutate_autonomy`` (``manual`` then ``restore``), not bare
``%auto``.
"""

from __future__ import annotations

import uuid

from . import harness
from .rows import APPROVE_ARCHIVE, ASK, FIRST
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def test_tale_a_off_on_restores_tale(tmp_path, monkeypatch) -> None:
    """Off then on round-trips a ``:tale`` agent through real gates."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    _, _, artifacts_dir = harness.launch_meta("%auto:tale\nDo the work", workdir)
    harness.adapt_a_off(artifacts_dir)
    toggled = harness.adapt_a_on_bare(artifacts_dir)

    tag = uuid.uuid4().hex[:8]
    assert (
        harness.plan_outcome(
            toggled,
            artifacts_dir,
            tale_plan,
            monkeypatch=monkeypatch,
            request_id=f"tale-{tag}",
        )
        == APPROVE_ARCHIVE
    )
    assert (
        harness.plan_outcome(
            toggled,
            artifacts_dir,
            epic_plan,
            monkeypatch=monkeypatch,
            request_id=f"epic-{tag}",
        )
        == ASK
    )
    assert (
        harness.question_outcome(
            artifacts_dir, monkeypatch=monkeypatch, request_id=f"q-{tag}"
        )
        == FIRST
    )

"""Public import path for the bead-task-triage chop."""

from sase.scripts import sase_chop_bead_task_triage as public_chop
from sase.scripts import _bead_task_triage_reconcile as implementation


def test_public_facade_exports_only_the_chop_api() -> None:
    assert public_chop.main is implementation.main
    assert public_chop.AUTOMATION_OWNED_KINDS == implementation.AUTOMATION_OWNED_KINDS
    assert not hasattr(public_chop, "_run")

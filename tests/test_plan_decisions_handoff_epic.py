"""Epic-context tests for Plan Decisions handoff.

Split from ``tests.test_plan_decisions_handoff``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._plan_decisions_handoff_helpers import STAMPED_EPIC, STAMPED_TALE

__all__ = [
    "test_epic_context_fails_closed",
    "test_epic_context_phase_bead_parent_design_and_successor",
    "test_epic_context_resolves_plan_ref_and_skips_missing",
    "test_epic_context_resolves_snapshot_and_inherits",
]


def test_epic_context_resolves_snapshot_and_inherits(tmp_path: Path) -> None:
    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"epic_plan_snapshot": str(epic_path)}), encoding="utf-8"
    )
    sub_path = tmp_path / "phase_sub.md"
    sub_path.write_text(STAMPED_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import (
        coder_decisions_block,
        epic_decision_context,
    )

    context = epic_decision_context(artifacts)
    assert context is not None
    assert context.decided_by == "reviewer"
    block = coder_decisions_block(sub_path, audience="epic_phase", inherited=context)
    assert "Inherited from epic" in block


def test_epic_context_fails_closed(tmp_path: Path) -> None:
    from sase.sdd.plan_decision_handoff import epic_decision_context

    assert epic_decision_context(tmp_path / "missing") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert epic_decision_context(empty) is None
    (empty / "agent_meta.json").write_text("{}", encoding="utf-8")
    assert epic_decision_context(empty) is None


def test_epic_context_resolves_plan_ref_and_skips_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from sase.bead.cli_detail_context import plan_reference_roots
    from sase.sdd.plan_decision_handoff import epic_decision_context

    monkeypatch.chdir(tmp_path)
    roots = plan_reference_roots()
    assert roots, "expected default plan roots for epic ref test"
    dest = roots[0] / "202610" / "epic.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(STAMPED_EPIC, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"epic_plan_ref": "plan:202610/epic.md"}), encoding="utf-8"
    )
    context = epic_decision_context(artifacts)
    assert context is not None
    assert context.decided_by == "reviewer"

    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"epic_plan_ref": "plan:202610/missing.md"}),
        encoding="utf-8",
    )
    assert epic_decision_context(artifacts) is None
    assert dest.is_file()


def test_epic_context_phase_bead_parent_design_and_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json
    from types import SimpleNamespace as _NS

    import sase.sdd.plan_decision_handoff as _handoff

    monkeypatch.chdir(tmp_path)
    from sase.bead.cli_detail_context import plan_reference_roots as _roots

    roots = _roots()
    assert roots
    dest = roots[0] / "202610" / "epic.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(STAMPED_EPIC, encoding="utf-8")

    phase_detail = _NS(
        issue=_NS(parent_id="sase-1hi.10"),
        plan=_NS(path="plan:202610/epic.md"),
    )

    def _fake_design(bead_id: str) -> str | None:
        assert bead_id == "sase-1hi.10"
        return "plan:202610/epic.md"

    monkeypatch.setattr(_handoff, "_bead_design_plan", _fake_design)

    import sase.bead.cli_common as _common
    import sase.bead.cli_detail_resolution as _resolution

    class _FakeView:
        def __enter__(self) -> _FakeView:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(_common, "get_read_view", lambda: _FakeView())
    monkeypatch.setattr(
        _resolution, "resolve_issue_detail", lambda view, bead_id, **kw: phase_detail
    )

    artifacts = tmp_path / "phase-artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"phase_bead_id": "sase-1hi.10.2"}), encoding="utf-8"
    )
    context = _handoff.epic_decision_context(artifacts)
    assert context is not None
    assert context.decided_by == "reviewer"

    coder = tmp_path / "coder-artifacts"
    coder.mkdir()
    (coder / "agent_meta.json").write_text(
        _json.dumps({"parent_timestamp": artifacts.name}), encoding="utf-8"
    )
    successor = _handoff.epic_decision_context(coder)
    assert successor is not None
    assert successor.decided_by == "reviewer"

    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"phase_bead_id": "sase-missing"}), encoding="utf-8"
    )

    def _raise_detail(view: object, bead_id: str, **kw: object) -> object:
        raise ValueError("missing bead")

    monkeypatch.setattr(_resolution, "resolve_issue_detail", _raise_detail)
    assert _handoff.epic_decision_context(artifacts) is None

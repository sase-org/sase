"""Keep-work recovery target resolution: actions, models, lineage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack.recover_common import (
    RecoveryRefusal,
    admission_binding_for,
    new_launch_identity,
    predecessor_concrete_target,
)
from sase.agent.hijack.recover_subject import lineage_for, session_base_for
from sase.agent.hijack.recover_target import (
    conflicting_launch_directives,
    extract_prompt_model,
    require_concrete_target,
    resolve_effective_target,
)


def _record(artifacts: Path, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 1,
        "hijack_id": "h-123",
        "agent_name": "acme--3",
        "artifacts_dir": str(artifacts),
        "session": "acme",
        "project_file": "/tmp/proj.sase",
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "pid": 111,
        "provider": "claude",
        "model": "opus",
        "effort": "high",
        "state": "held",
        "revision": 7,
    }
    record.update(overrides)
    return record


class TestConcreteTargets:
    def test_continue_pins_predecessor_concrete(self) -> None:
        record = _record(Path("/tmp/x"), provider="claude", model="opus")
        assert predecessor_concrete_target(record) == "claude/opus@high"

    def test_bare_model_without_provider(self) -> None:
        record = _record(Path("/tmp/x"), provider=None, model="opus")
        assert predecessor_concrete_target(record) == "opus@high"

    def test_missing_model_is_none(self) -> None:
        assert predecessor_concrete_target(_record(Path("/tmp/x"), model="")) is None

    def test_require_concrete_target_accepts_effort(self) -> None:
        assert (
            require_concrete_target("claude/opus@xhigh", source="t")
            == "claude/opus@xhigh"
        )

    @pytest.mark.parametrize("value", ["opus", "@large", "claude/", "claude/@high", ""])
    def test_require_concrete_target_refuses(self, value: str) -> None:
        with pytest.raises(RecoveryRefusal):
            require_concrete_target(value, source="t")


class TestEffectiveTargets:
    def _row(self, **overrides: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "available": True,
            "reason": None,
            "target": "claude/opus@high",
        }
        row.update(overrides)
        return row

    def test_continue_uses_preview_target(self) -> None:
        record = _record(Path("/tmp/x"))
        target = resolve_effective_target(
            action="continue", record=record, preview_action=self._row()
        )
        assert target.concrete_target == "claude/opus@high"
        assert target.model_changed is False

    def test_escalate_pins_preview_target(self) -> None:
        record = _record(Path("/tmp/x"))
        target = resolve_effective_target(
            action="escalate",
            record=record,
            preview_action=self._row(target="claude/opus@xhigh"),
        )
        assert target.concrete_target == "claude/opus@xhigh"
        assert target.model_changed is True

    def test_unavailable_action_refuses(self) -> None:
        record = _record(Path("/tmp/x"))
        with pytest.raises(RecoveryRefusal, match="unavailable"):
            resolve_effective_target(
                action="escalate",
                record=record,
                preview_action=self._row(available=False, reason="top rung"),
            )

    def test_unknown_action_refuses(self) -> None:
        with pytest.raises(RecoveryRefusal, match="one of"):
            resolve_effective_target(
                action="restart",
                record=_record(Path("/tmp/x")),
                preview_action=self._row(),
            )

    def test_continue_rejects_options(self) -> None:
        with pytest.raises(RecoveryRefusal, match="takes no"):
            resolve_effective_target(
                action="continue",
                record=_record(Path("/tmp/x")),
                preview_action=self._row(),
                model_override="claude/sonnet@high",
            )

    def test_instruct_requires_prompt(self) -> None:
        with pytest.raises(RecoveryRefusal, match="replacement prompt"):
            resolve_effective_target(
                action="instruct",
                record=_record(Path("/tmp/x")),
                preview_action=self._row(),
            )

    def test_instruct_prompt_model_overrides_continue(self) -> None:
        record = _record(Path("/tmp/x"))
        target = resolve_effective_target(
            action="instruct",
            record=record,
            preview_action=self._row(),
            prompt_text="%model:claude/sonnet@high\n\nDo it differently.",
        )
        assert target.concrete_target == "claude/sonnet@high"
        assert target.model_changed is True
        assert target.prompt.startswith("%model:claude/sonnet@high")

    def test_instruct_explicit_model_wins(self) -> None:
        record = _record(Path("/tmp/x"))
        target = resolve_effective_target(
            action="instruct",
            record=record,
            preview_action=self._row(),
            model_override="claude/sonnet@low",
            prompt_text="%model:claude/opus@high\n\nDo it differently.",
        )
        assert target.concrete_target == "claude/sonnet@low"
        assert "%model:claude/sonnet@low" in target.prompt

    def test_instruct_without_model_keeps_stalled(self) -> None:
        record = _record(Path("/tmp/x"))
        target = resolve_effective_target(
            action="instruct",
            record=record,
            preview_action=self._row(),
            prompt_text="Just guidance, no model edit.",
        )
        assert target.concrete_target == "claude/opus@high"
        assert target.model_changed is False

    def test_instruct_bare_model_inherits_provider(self) -> None:
        record = _record(Path("/tmp/x"))
        target = resolve_effective_target(
            action="instruct",
            record=record,
            preview_action=self._row(),
            prompt_text="%model:sonnet@low\n\nNarrower model.",
        )
        assert target.concrete_target == "claude/sonnet@low"

    def test_instruct_alias_model_refuses(self) -> None:
        with pytest.raises(RecoveryRefusal, match="concrete"):
            resolve_effective_target(
                action="instruct",
                record=_record(Path("/tmp/x")),
                preview_action=self._row(),
                prompt_text="%model:@large\n\nAlias pick.",
            )

    def test_instruct_identity_conflict_refuses(self) -> None:
        with pytest.raises(RecoveryRefusal, match="launch directives"):
            resolve_effective_target(
                action="instruct",
                record=_record(Path("/tmp/x")),
                preview_action=self._row(),
                prompt_text="%id(other)\n\nHijack the launch.",
            )

    def test_instruct_wait_conflict_refuses(self) -> None:
        with pytest.raises(RecoveryRefusal, match="launch directives"):
            resolve_effective_target(
                action="instruct",
                record=_record(Path("/tmp/x")),
                preview_action=self._row(),
                prompt_text="%wait(other)\n\nWait for someone.",
            )

    def test_fenced_directives_are_inert(self) -> None:
        assert (
            conflicting_launch_directives("Task:\n```\n%id(other)\n```\nReal work.")
            == []
        )
        assert (
            extract_prompt_model(
                "Task:\n```\n%model:other\n```\n%model:claude/sonnet@high\nWork."
            )
            == "claude/sonnet@high"
        )


class TestAdmissionBinding:
    def test_stable_for_same_resolution(self) -> None:
        first = admission_binding_for("h-1", "launch-1", "acme--4", "claude/opus")
        second = admission_binding_for("h-1", "launch-1", "acme--4", "claude/opus")
        assert first == second
        assert first["admission_request_id"].startswith("hijack-recover-h-1-")

    def test_unique_per_launch_identity(self) -> None:
        first = admission_binding_for("h-1", "launch-1", "acme--4", "claude/opus")
        second = admission_binding_for("h-1", "launch-2", "acme--4", "claude/opus")
        assert first != second

    def test_launch_identities_unique(self) -> None:
        assert new_launch_identity() != new_launch_identity()


class TestSessionAndLineage:
    def test_session_prefers_record(self) -> None:
        record = _record(Path("/tmp/x"), session="sess")
        assert session_base_for(record, {"agent_session": "other"}) == "sess"

    def test_session_falls_back_to_meta_then_name(self) -> None:
        record = _record(Path("/tmp/x"), session=None)
        assert session_base_for(record, {"agent_session": "meta-sess"}) == "meta-sess"
        assert session_base_for(record, {}) == "acme"
        assert (
            session_base_for(
                _record(Path("/tmp/x"), agent_name="solo", session=None), {}
            )
            is None
        )

    def test_lineage_uses_concrete_rungs(self) -> None:
        record = _record(Path("/tmp/x"))
        target = resolve_effective_target(
            action="escalate",
            record=record,
            preview_action={
                "available": True,
                "reason": None,
                "target": "claude/opus@xhigh",
            },
        )
        lineage = lineage_for(hijack_id="h-123", record=record, target=target)
        assert lineage.as_dict() == {
            "hijack_id": "h-123",
            "from_rung": "claude/opus@high",
            "to_rung": "claude/opus@xhigh",
            "predecessor": "acme--3",
        }

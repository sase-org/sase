"""release transactions and preview rows tests for hijack release recovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover_common import RecoveryResult
from sase.agent.hijack.recover_release import (
    recover_release_action,
    restart_availability_reason,
    restart_replacement_conflicts,
)
from tests._agent_hijack_recover_helpers import record as make_record
from tests._agent_hijack_recover_helpers import subject as make_subject


from tests._agent_hijack_recover_release_support import (
    ReleaseLedger,
    ReleasePreview,
    ReleaseRow,
    held_artifacts,
    install_release_ledger,
    recover_args,
    record_for,
    release_deps,
    release_preview,
    release_preview_for_cli,
    release_subject,
)


class TestReleaseTransaction:
    def _held(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any
    ) -> tuple[ReleaseLedger, dict[str, Any]]:
        artifacts = held_artifacts(tmp_path)
        rec = make_record(artifacts, **overrides)
        fake = ReleaseLedger(rec)
        install_release_ledger(monkeypatch, fake)
        return fake, rec

    def test_dismiss_settles_dismissed_and_releases_bead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "launched", result.message
        assert fake.current["state"] == "dismissed"
        assert fake.current["resolution_action"] == "dismiss"
        assert calls["snapshots"] == 1
        assert calls["dismiss"] == 1
        assert calls["bead"] == 1
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"]["state"] == "dismissed"
        assert done["recovery"]["action"] == "dismiss"

    def test_restart_keeps_bead_and_settles_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="restart", deps=deps)

        assert result.kind == "launched", result.message
        assert result.successor == "acme--3"
        assert fake.current["state"] == "resolved"
        assert fake.current["resolution_action"] == "restart"
        assert calls["snapshots"] == 1
        assert calls["bead"] == 0
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["recovery"]["state"] == "resolved"
        assert done["recovery"]["action"] == "restart"
        assert done["recovery"]["successor"] == "acme--3"

    def test_restart_with_replacement_runs_edit_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3", action="restart", prompt="Do the other thing.\n", deps=deps
        )

        assert result.kind == "launched", result.message
        assert result.successor == "acme--3"
        assert fake.current["state"] == "resolved"
        assert fake.current["resolution_action"] == "edit"
        assert calls["dismiss"] == 1
        assert calls["bead"] == 1

    def test_replacement_conflicts_refuse_before_cas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3",
            action="restart",
            prompt="%wait(acme--9)\n\nDo the other thing.\n",
            deps=deps,
        )

        assert result.kind == "refused"
        assert result.detail.get("code") == "conflicting_directives"
        assert fake.events == []
        assert calls["snapshots"] == 0

    def test_snapshot_failure_returns_to_held(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview(), snapshot="fail")
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "error"
        assert result.detail.get("code") == "snapshot_failed"
        assert fake.current["state"] == "held"
        assert calls["dismiss"] == 0

    def test_discard_without_snapshot_bypasses_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview(), snapshot="fail")
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3", action="dismiss", discard_without_snapshot=True, deps=deps
        )

        assert result.kind == "launched", result.message
        assert fake.current["state"] == "dismissed"

    def test_preview_refusal_blocks_before_cas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(
            preview=release_preview(restart="fanout: fan-out prompt")
        )
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="restart", deps=deps)

        assert result.kind == "refused"
        assert result.detail.get("code") == "action_unavailable"
        assert "fan-out prompt" in (result.message or "")
        assert fake.events == []

    def test_stale_revision_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, _ = release_deps(preview=release_preview(revision=7))
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3", action="dismiss", expected_revision=6, deps=deps
        )

        assert result.kind == "refused"
        assert result.detail.get("code") == "stale_revision"
        assert fake.events == []

    def test_repeat_resolution_reports_without_acting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch, state="dismissed")
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "already_resolved"
        assert calls["snapshots"] == 0
        assert calls["dismiss"] == 0

    def test_expired_hold_allows_release(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch, state="expired")
        deps, _ = release_deps(preview=release_preview(state="expired"))
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "launched", result.message
        assert fake.current["state"] == "dismissed"

    def test_unsupported_action_and_state_refuse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, _ = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        bad_action = recover_release_action("acme--3", action="escalate", deps=deps)
        assert bad_action.kind == "refused"
        assert bad_action.detail.get("code") == "unsupported_action"

        stopped = make_record(held_artifacts(tmp_path), state="stop_failed")
        deps.load_subject = lambda name: make_subject(stopped)
        bad_state = recover_release_action("acme--3", action="dismiss", deps=deps)
        assert bad_state.kind == "refused"
        assert bad_state.detail.get("code") == "not_held"

    def test_failed_relaunch_after_release_stays_uncertain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, _ = release_deps(preview=release_preview(), execute_status="partial")
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="restart", deps=deps)

        assert result.kind == "uncertain"
        assert fake.current["state"] == "resolving"
        assert result.detail.get("recovery_command") == "sase run --recovery abc"


class TestRestartAvailability:
    def test_planner_success_means_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.recover_release as release_module

        monkeypatch.setattr(
            release_module, "_default_plan_restart", lambda name: object()
        )
        assert restart_availability_reason({"agent_name": "acme--3"}) is None

    def test_planner_refusal_becomes_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.recover_release as release_module
        from sase.agent._restart_types import AgentRestartError

        def refuse(name: str) -> Any:
            raise AgentRestartError(reason="fanout", message="fan-out prompt")

        monkeypatch.setattr(release_module, "_default_plan_restart", refuse)
        reason = restart_availability_reason({"agent_name": "acme--3"})
        assert reason is not None
        assert "fanout" in reason
        assert "fan-out prompt" in reason

    def test_missing_name_refuses(self) -> None:
        assert restart_availability_reason({}) is not None


class TestReplacementConflicts:
    def test_clean_prompt_has_no_conflicts(self) -> None:
        assert restart_replacement_conflicts("Do the other thing.\n") == []

    def test_changed_id_is_allowed(self) -> None:
        assert (
            restart_replacement_conflicts("%id acme--9\n\nDo the other thing.\n") == []
        )

    def test_wait_dependency_conflicts(self) -> None:
        conflicts = restart_replacement_conflicts(
            "%wait(acme--9)\n\nDo the other thing.\n"
        )
        assert any("wait" in item for item in conflicts)

    def test_directive_only_prompt_conflicts(self) -> None:
        conflicts = restart_replacement_conflicts("%id(acme--9)\n")
        assert conflicts != []

    def test_unknown_alias_model_fails_closed(self) -> None:
        from sase.agent.hijack.recover_common import RecoveryRefusal

        with pytest.raises(RecoveryRefusal) as excinfo:
            restart_replacement_conflicts(
                "%model:@no-such-alias-xyz\n\nDo the thing.\n"
            )
        assert excinfo.value.code == "invalid_prompt"

    def test_concrete_model_is_allowed(self) -> None:
        assert (
            restart_replacement_conflicts("%model:claude/opus@high\n\nDo the thing.\n")
            == []
        )


class TestReleasePreviewRows:
    def _wire(
        self,
        state: str = "held",
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "hijack_id": "h-123",
            "revision": 7,
            "header": {},
            "default_action": "escalate",
            "actions": [
                {
                    "action": "escalate",
                    "available": True,
                    "reason": None,
                    "label": "Escalate",
                    "detail": "up",
                    "target": "t",
                },
                {
                    "action": "continue",
                    "available": True,
                    "reason": None,
                    "label": "Continue",
                    "detail": "same",
                    "target": "t",
                },
                {
                    "action": "restart",
                    "available": False,
                    "reason": "not yet available",
                    "label": "Restart",
                    "detail": "",
                    "target": None,
                },
                {
                    "action": "dismiss",
                    "available": False,
                    "reason": "not yet available",
                    "label": "Dismiss",
                    "detail": "",
                    "target": None,
                },
            ],
        }

    def test_held_preview_marks_release_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.agent.hijack import _preview_recovery as preview_module

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: None,
        )
        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "held"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        assert by_action["restart"]["available"] is True
        assert by_action["restart"]["detail"] == (
            "same prompt, same name, fresh workspace"
        )
        assert by_action["edit"]["available"] is True
        assert by_action["edit"]["label"] == "Edit"
        assert by_action["dismiss"]["available"] is True
        assert by_action["dismiss"]["detail"] == (
            "snapshot first, then workspace released"
        )

    def test_planner_refusal_disables_restart_but_keeps_dismiss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.agent.hijack import _preview_recovery as preview_module

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: "fanout: fan-out prompt",
        )
        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "held"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        assert by_action["restart"]["available"] is False
        assert "fan-out prompt" in (by_action["restart"]["reason"] or "")
        assert by_action["edit"]["available"] is True
        assert by_action["dismiss"]["available"] is True

    def test_resolving_disables_every_release_row(self) -> None:
        from sase.agent.hijack import _preview_recovery as preview_module

        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "resolving"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        for name in ("restart", "edit", "dismiss"):
            assert by_action[name]["available"] is False
            assert by_action[name]["reason"] == "already being resolved"

    def test_expired_offers_only_release_actions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.agent.hijack import _preview_recovery as preview_module

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: None,
        )
        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "expired"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        for name in ("restart", "edit", "dismiss"):
            assert by_action[name]["available"] is True

    def test_preview_end_to_end_patches_release_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.agent.hijack import _preview_recovery as preview_module

        artifacts = held_artifacts(tmp_path)
        monkeypatch.setattr(
            preview_module,
            "agent_hijack_config",
            lambda: preview_module.AgentHijackConfig(),
        )
        monkeypatch.setattr(preview_module, "build_alias_candidates", lambda ladder: {})
        monkeypatch.setattr(
            preview_module,
            "hijack_escalation_target",
            lambda request: {
                "available": False,
                "kind": None,
                "reason": "no model",
                "concrete": None,
            },
        )

        def assemble(request: dict[str, Any]) -> dict[str, Any]:
            return self._wire(state=request.get("state", "held"))

        monkeypatch.setattr(
            preview_module, "assemble_hijack_recovery_preview", assemble
        )
        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: None,
        )
        record = make_record(artifacts, artifacts_dir=str(artifacts), state="held")
        preview = preview_module.hijack_recovery_preview(record)
        assert preview.action("restart") is not None
        assert preview.action("restart").available is True  # type: ignore[union-attr]
        assert preview.action("dismiss").available is True  # type: ignore[union-attr]
        assert preview.action("edit").available is True  # type: ignore[union-attr]

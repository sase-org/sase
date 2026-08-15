"""Tests for permanent agent-name launch validation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.proc_queue import ProcInfo
from sase.agent.launch_validation import (
    AgentNameForeignMachineError,
    AgentNameLaunchCollisionError,
    AgentNameReuseConfirmationRequiredError,
    AgentNameSyntaxError,
    INTERNAL_AGENT_NAME_BYPASS_ENV,
    force_reuse_bead_associations_by_prompt,
    force_reuse_owner_names,
    internal_agent_name_bypass_enabled,
    preflight_launch_name_requests,
    rewrite_force_reuse_name_directives,
    validate_user_agent_name,
    validate_launch_name_requests,
    wipe_names_for_forced_reuse,
)
from sase.agent.launch_validation import (
    _AgentNameClanCollisionError as AgentNameClanCollisionError,
)
from sase.agent.launch_validation import (
    _AgentNameFamilyCollisionError as AgentNameFamilyCollisionError,
)


def _make_agent(home: Path, name: str, suffix: str = "run-old") -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": name, "pid": 123}),
        encoding="utf-8",
    )
    return artifacts_dir


def test_extracts_forced_reuse_name_request() -> None:
    names = force_reuse_owner_names(["%id:!foo\nDo work"])

    assert names == ["foo"]


def test_extracts_forced_reuse_clan_member_name_request() -> None:
    names = force_reuse_owner_names(["%id(!worker, clan=research)\nDo work"])

    assert names == ["research.worker"]


def test_extracts_forced_reuse_bead_association_for_clan_member() -> None:
    associations = force_reuse_bead_associations_by_prompt(
        ["%i(!3, clan=sase-hq, bead=sase-hq.3)\nDo work"]
    )

    assert associations[0] is not None
    assert associations[0].owner_name == "sase-hq.3"
    assert associations[0].bead_id == "sase-hq.3"


def test_extracts_forced_reuse_bead_association_for_family_member() -> None:
    associations = force_reuse_bead_associations_by_prompt(
        ["%id(!reviewer, family=foo, bead=sase-1.2)\nDo work"]
    )

    assert associations[0] is not None
    assert associations[0].owner_name == "foo--reviewer"
    assert associations[0].bead_id == "sase-1.2"


def test_forced_reuse_bead_association_ignores_protected_regions() -> None:
    associations = force_reuse_bead_associations_by_prompt(
        [
            "```text\n%id(!hidden, bead=sase-hidden)\n```\n"
            "%xprompts_enabled:false\n"
            "%id(!disabled, bead=sase-disabled)\n"
            "%xprompts_enabled:true\n\n"
            "%id(!worker, bead=sase-1)\nDo work"
        ]
    )

    assert associations[0] is not None
    assert associations[0].owner_name == "worker"
    assert associations[0].bead_id == "sase-1"


def test_forced_reuse_bead_association_absent_without_force_or_bead() -> None:
    associations = force_reuse_bead_associations_by_prompt(
        ["%id(worker, bead=sase-1)\nDo work", "%id:!worker\nDo work"]
    )

    assert associations == [None, None]


def test_forced_reuse_bead_association_preflight_rejects_duplicates() -> None:
    with pytest.raises(RuntimeError, match="Ambiguous forced bead authorization"):
        preflight_launch_name_requests(
            [
                "%id(!worker, bead=sase-1)\n"
                "%i(!reviewer, family=foo, bead=sase-2)\nDo work"
            ],
            allow_force_reuse=True,
        )


def test_rewrites_forced_reuse_to_normal_name_directive() -> None:
    prompt = "%id:!foo\nDo work"

    assert rewrite_force_reuse_name_directives(prompt) == "%id:foo\nDo work"


def test_rewrites_forced_reuse_clan_member_without_losing_membership() -> None:
    prompt = "%id(!worker, clan=research)\nDo work"

    assert rewrite_force_reuse_name_directives(prompt) == (
        "%id(worker, clan=research)\nDo work"
    )


def test_collision_validation_uses_registry_suggestion(tmp_path: Path) -> None:
    _make_agent(tmp_path, "sasefoo")

    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(AgentNameLaunchCollisionError, match="Try 'sasefoo1'"):
            validate_launch_name_requests(["%id:sasefoo\nDo work"])


def test_collision_validation_suggests_clan_hood_name(tmp_path: Path) -> None:
    from sase.agent.names import reserve_registered_clan_name

    artifacts_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_clan_name("research", "run0", artifacts_dir)
        with pytest.raises(
            AgentNameClanCollisionError,
            match=r"inside the clan hood.*research\.member",
        ):
            validate_launch_name_requests(["%id:research\nDo work"])
        with pytest.raises(AgentNameClanCollisionError, match="reserved for clan"):
            validate_launch_name_requests(
                ["%id:!research\nDo work"], allow_force_reuse=True
            )


def test_collision_validation_preserves_family_container(tmp_path: Path) -> None:
    from sase.agent.names import (
        claim_registered_name,
        convert_registered_agent_to_family,
    )

    artifacts_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/run1"
    artifacts_dir.mkdir(parents=True)
    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("review", artifacts_dir)
        convert_registered_agent_to_family("review", "review--0", artifacts_dir)
        with pytest.raises(
            AgentNameFamilyCollisionError,
            match=r"Attach a member with %i\(suffix, family=parent\)",
        ):
            validate_launch_name_requests(["%id:review\nDo work"])
        with pytest.raises(
            AgentNameFamilyCollisionError, match="reserved for agent family"
        ):
            validate_launch_name_requests(
                ["%id:!review\nDo work"], allow_force_reuse=True
            )


def test_forced_reuse_requires_confirmation_on_non_tui_surfaces() -> None:
    with pytest.raises(AgentNameReuseConfirmationRequiredError, match="confirmation"):
        validate_launch_name_requests(["%id:!foo\nDo work"])


def test_forced_family_attach_requires_confirmation_and_derives_exact_owner() -> None:
    prompt = "%id(!code, family=foo)\nDo work"

    with pytest.raises(AgentNameReuseConfirmationRequiredError, match="foo--code"):
        validate_launch_name_requests([prompt])

    preflight_launch_name_requests([prompt], allow_force_reuse=True)
    assert force_reuse_owner_names([prompt]) == ["foo--code"]
    assert rewrite_force_reuse_name_directives(prompt) == (
        "%id(code, family=foo)\nDo work"
    )


def test_forced_family_attach_does_not_relax_direct_family_shaped_names() -> None:
    preflight_launch_name_requests(
        ["%id(!code, family=foo)\nDo work"],
        allow_force_reuse=True,
    )
    with pytest.raises(AgentNameSyntaxError, match="foo--code"):
        preflight_launch_name_requests(
            ["%id:!foo--code\nDo work"],
            allow_force_reuse=True,
        )


def test_forced_reuse_wipe_result_errors_abort_launch_cleanup() -> None:
    from sase.agent.names import AgentNameWipeResult

    with (
        patch(
            "sase.agent.names.wipe_agent_name_for_reuse",
            return_value=AgentNameWipeResult(
                target_name="foo--code",
                found=True,
                errors=("artifact removal failed",),
            ),
        ),
        pytest.raises(RuntimeError, match="artifact removal failed"),
    ):
        wipe_names_for_forced_reuse(["foo--code"])


def test_validation_loads_reserved_name_set_once_for_many_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reserved-name set is loaded once per launch, not once per name."""
    calls = {"count": 0}

    def counting_reserved() -> set[str]:
        calls["count"] += 1
        return set()

    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", counting_reserved)

    validate_launch_name_requests([f"%id:agent{i}\nDo work" for i in range(8)])

    assert calls["count"] == 1


def test_user_agent_names_cannot_contain_reserved_family_separator() -> None:
    validate_user_agent_name("foo-bar")
    with pytest.raises(AgentNameSyntaxError, match="cannot contain '--'"):
        validate_user_agent_name("foo--bar")


def test_known_foreign_machine_name_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )

    validate_user_agent_name("foo")
    validate_user_agent_name("athena.foo")
    with pytest.raises(AgentNameForeignMachineError, match="known machine 'zeus'"):
        validate_user_agent_name("zeus.foo")


def test_name_directive_allows_hyphenated_name_before_launch() -> None:
    validate_launch_name_requests(["%id:foo-bar\nDo work"])


def test_name_directive_rejects_reserved_family_separator_before_launch() -> None:
    with pytest.raises(AgentNameSyntaxError, match="foo--bar"):
        validate_launch_name_requests(["%id:foo--bar\nDo work"])


def test_id_clan_keyword_validates_derived_name_before_launch() -> None:
    validate_launch_name_requests(["%id(worker, clan=research)\nDo work"])

    with pytest.raises(AgentNameSyntaxError, match="research.foo--bar"):
        validate_launch_name_requests(["%id(foo--bar, clan=research)\nDo work"])


def test_id_clan_keyword_validates_derived_template_before_launch() -> None:
    with pytest.raises(RuntimeError, match="exactly one '@' marker"):
        validate_launch_name_requests(["%id(@, clan=research.@)\nDo work"])


def test_name_directive_allows_template_before_launch(tmp_path: Path) -> None:
    _make_agent(tmp_path, "foo-1")

    with patch.object(Path, "home", return_value=tmp_path):
        validate_launch_name_requests(["%id:foo-@\nDo work"])
        validate_launch_name_requests(["%id:@.cld\nDo work"])


def test_duplicate_indexed_templates_are_not_exact_name_collisions(
    tmp_path: Path,
) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        validate_launch_name_requests(["%id:foo-@\nFirst", "%id:foo-@\nSecond"])


def test_direct_generated_family_name_remains_invalid() -> None:
    with pytest.raises(AgentNameSyntaxError, match="foo--1"):
        validate_launch_name_requests(["%id:foo--1\nDo work"])


def test_template_rendering_rejects_reserved_family_separator() -> None:
    with pytest.raises(AgentNameSyntaxError, match="foo--0"):
        validate_launch_name_requests(["%id:foo--@\nDo work"])


def test_forced_reuse_template_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="forced reuse"):
        validate_launch_name_requests(["%id:!foo-@\nDo work"])
    with pytest.raises(RuntimeError, match="forced reuse"):
        validate_launch_name_requests(["%id:!@.cld\nDo work"])


def test_force_reuse_owner_names_ignores_templates() -> None:
    names = force_reuse_owner_names(
        ["%id:!foo-@\nDo work", "%id:!@.cld\nMore", "%id:!bar\nMore"]
    )

    assert names == ["bar"]


def test_forced_reuse_name_directive_rejects_separator_after_bang_strip() -> None:
    with pytest.raises(AgentNameSyntaxError, match="foo--bar"):
        validate_launch_name_requests(["%id:!foo--bar\nDo work"])


def test_forced_reuse_preflight_rejects_separator_before_cleanup() -> None:
    with pytest.raises(AgentNameSyntaxError, match="foo--bar"):
        preflight_launch_name_requests(
            ["%id:!foo--bar\nDo work"],
            allow_force_reuse=True,
        )


def test_forced_reuse_preflight_defers_existing_name_collision(
    tmp_path: Path,
) -> None:
    _make_agent(tmp_path, "foo")

    with patch.object(Path, "home", return_value=tmp_path):
        preflight_launch_name_requests(
            ["%id:!foo\nDo work"],
            allow_force_reuse=True,
        )


def test_internal_bypass_allows_reserved_family_separator_system_names(
    tmp_path: Path,
) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        validate_launch_name_requests(
            ["%id:sase--42.3\nDo work"],
            allow_reserved_family_separator_names=True,
        )
    assert internal_agent_name_bypass_enabled({INTERNAL_AGENT_NAME_BYPASS_ENV: "1"})


def test_tui_agent_rename_rejects_reserved_family_separator_name(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.actions.rename import RenameMixin

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")

    class FakeAgent:
        identity = ("workflow", "cl", "raw")
        agent_name = None
        cl_name = "cl"
        display_name = "cl"

        def get_artifacts_dir(self) -> str:
            return str(artifacts_dir)

    class FakeApp(RenameMixin):
        def __init__(self) -> None:
            self._agents = [FakeAgent()]
            self.notifications: list[tuple[str, str | None]] = []

        def _get_selected_agent(self) -> FakeAgent:
            return self._agents[0]

        def notify(self, message: str, severity: str | None = None) -> None:
            self.notifications.append((message, severity))

        def push_screen(self, _screen, callback) -> None:
            callback("foo--bar")

        def _refresh_agents_display(self, *, list_changed: bool) -> None:
            raise AssertionError("invalid rename should not refresh")

    app = FakeApp()
    app._set_agent_name()

    assert app.notifications == [
        (
            "Agent name 'foo--bar' cannot contain '--'; double dash is "
            "reserved for agent-family phases.",
            "error",
        )
    ]
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {"pid": 123}


def test_tui_agent_rename_refreshes_artifact_index(tmp_path: Path) -> None:
    from sase.ace.tui.actions.rename import RenameMixin

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")

    class FakeAgent:
        identity = ("workflow", "cl", "raw")
        agent_name = None
        cl_name = "cl"
        display_name = "cl"

        def get_artifacts_dir(self) -> str:
            return str(artifacts_dir)

    class FakeApp(RenameMixin):
        def __init__(self) -> None:
            self._agents = [FakeAgent()]
            self.notifications: list[tuple[str, str | None]] = []
            self.refresh_calls = 0

        def _get_selected_agent(self) -> FakeAgent:
            return self._agents[0]

        def notify(self, message: str, severity: str | None = None) -> None:
            self.notifications.append((message, severity))

        def push_screen(self, _screen, callback) -> None:
            callback("agentname")

        def _refresh_agents_display(self, *, list_changed: bool) -> None:
            self.refresh_calls += 1

        def _submit_durable_proc(
            self,
            argv: Any,
            *,
            operation: str = "",
            request: Any = None,
            request_fingerprint: str = "",
            concurrency_keys: Any = (),
            proc_type: str | None = None,
            display_name: str | None = None,
            cl_name: str = "",
            project_file: str = "",
            on_complete: Any = None,
            reload_on_complete: bool = True,
            notify_on_complete: bool = True,
            **kwargs: Any,
        ) -> ProcInfo:
            del argv, operation, request_fingerprint, concurrency_keys
            del reload_on_complete, notify_on_complete, kwargs
            payload = dict(request or {})

            def _callable() -> TrackedProcResult[Any]:
                from sase.ops.commands.agent import _persist_directive_from_payload

                _persist_directive_from_payload(
                    payload,
                    artifacts_dir=str(payload.get("artifacts_dir") or project_file),
                )
                return TrackedProcResult(success=True, message="ok", payload=payload)

            return self._submit_tracked_proc(
                proc_type or "agent-directive",
                cl_name,
                project_file,
                _callable,
                display_name=display_name,
                on_complete=on_complete,
            )

        def _submit_tracked_proc(
            self,
            proc_type: str,
            cl_name: str,
            project_file: str,
            proc_callable: Any,
            *,
            display_name: str | None = None,
            dedup_key: str | None = None,
            duplicate_message: str | None = None,
            on_complete: Any = None,
            reload_on_complete: bool = True,
            notify_on_complete: bool = True,
        ) -> ProcInfo:
            del duplicate_message, reload_on_complete, notify_on_complete
            proc_info = ProcInfo(
                proc_id="task-0",
                proc_type=proc_type,
                cl_name=cl_name,
                project_file=project_file,
                status="running",
                message="running",
                started_at=datetime.now(),
                display_name=display_name,
                dedup_key=dedup_key,
            )
            try:
                result = proc_callable()
            except Exception as exc:
                result = TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            proc_info.status = "success" if result.success else "error"
            proc_info.message = result.message
            proc_info.error = result.error
            if on_complete is not None:
                on_complete(
                    TrackedProcCompletion(
                        proc_info=proc_info,
                        success=result.success,
                        message=result.message,
                        output="",
                        payload=result.payload,
                        error=result.error,
                    )
                )
            return proc_info

    app = FakeApp()
    with (
        patch("sase.agent.names.claim_agent_name"),
        patch(
            "sase.ace.tui.actions.agents._directive_persistence."
            "update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        app._set_agent_name()

    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "pid": 123,
        "name": "agentname",
    }
    update_index.assert_called_once_with(str(artifacts_dir))
    assert app.refresh_calls == 1


def test_launch_agents_from_cwd_cancels_history_and_skips_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.history import prompt_store

    history_path = tmp_path / ".sase" / "prompt_history.json"
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_FILE", history_path)
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: (None, 0, "home"),
    )
    monkeypatch.setattr(
        "sase.agent.launcher.spawn_agent_subprocess",
        lambda **_kwargs: pytest.fail("spawn should not be called"),
    )

    from sase.agent.launcher import launch_agents_from_cwd

    prompt = "%id:bad--name\n#git:home Do work"
    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(AgentNameSyntaxError):
            launch_agents_from_cwd(prompt)

    entries = prompt_store.load_prompt_history()
    assert entries[0].text == prompt
    assert entries[0].cancelled is True

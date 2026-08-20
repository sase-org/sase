from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests._validate_sase_core_rs_tool_helpers import (
    load_validate_sase_core_rs,
    module_with_required_bindings,
)


pytestmark = pytest.mark.contract


def _proc_lifecycle_proc(**overrides: Any) -> dict[str, Any]:
    proc = {
        "schema_version": 3,
        "proc_id": "validator-proc",
        "status": "pending",
        "phase": "reserved",
        "lifecycle": "proc-shell",
        "reserved_by": "validate_sase_core_rs",
        "reserved_at": "2026-08-15T00:00:00Z",
        "request_fingerprint": "validator-fingerprint",
    }
    proc.update(overrides)
    return proc


def test_validate_proc_lifecycle_contract_passes_for_schema_v3_transitions() -> None:
    validator = load_validate_sase_core_rs()

    module = SimpleNamespace(
        reserve_proc=lambda *_args: {
            "schema_version": 3,
            "reserved": True,
            "replayed": False,
            "proc": _proc_lifecycle_proc(),
        },
        claim_proc_supervisor=lambda *_args: {
            "schema_version": 3,
            "matched": True,
            "proc": _proc_lifecycle_proc(
                status="running",
                started_at="2026-08-15T00:00:01Z",
                supervisor_id="validator-supervisor",
                supervisor_claimed_at="2026-08-15T00:00:01Z",
                pid=123,
                pgid=123,
            ),
        },
        request_proc_stop=lambda *_args: {
            "schema_version": 3,
            "matched": True,
            "proc": _proc_lifecycle_proc(
                status="running",
                stop_requested_by="validate_sase_core_rs",
                stop_requested_at="2026-08-15T00:00:02Z",
                stop_reason="probe",
            ),
        },
        begin_proc_settlement=lambda *_args: {
            "schema_version": 3,
            "matched": True,
            "proc": _proc_lifecycle_proc(
                status="settling",
                exit_code=0,
                message="settling",
                settling_started_at="2026-08-15T00:00:03Z",
            ),
        },
        finish_proc=lambda *_args: {
            "schema_version": 3,
            "matched": True,
            "proc": _proc_lifecycle_proc(
                status="success",
                finished_at="2026-08-15T00:00:04Z",
                finished_by="validator-supervisor",
                settled_at="2026-08-15T00:00:04Z",
                settled_by="validator-supervisor",
                result={"ok": True},
            ),
        },
    )

    assert validator._validate_proc_lifecycle_contract(module)


def test_validate_proc_lifecycle_contract_fails_on_stale_reserve_schema() -> None:
    validator = load_validate_sase_core_rs()
    module = SimpleNamespace(
        reserve_proc=lambda *_args: {
            "schema_version": 2,
            "reserved": True,
            "replayed": False,
            "proc": _proc_lifecycle_proc(schema_version=2),
        }
    )

    assert not validator._validate_proc_lifecycle_contract(module)


def test_validate_sase_core_rs_requires_current_artifact_ref_contract() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "artifact_ref_wire_schema_version": 5,
        "artifact_ref_context_wire_schema_version": 2,
        "artifact_ref_list_resolution_wire_schema_version": 2,
        "artifact_ref_path_filter_wire_schema_version": 1,
        "artifact_ref_file_index_wire_schema_version": 1,
    }

    assert bindings.keys() <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_artifact_ref_schemas(
        SimpleNamespace(
            **{name: lambda value=value: value for name, value in bindings.items()}
        )
    )
    for name, version in bindings.items():
        stale = dict(bindings)
        stale[name] = version + 1
        assert not validator._validate_artifact_ref_schemas(
            SimpleNamespace(
                **{
                    binding: lambda value=value: value
                    for binding, value in stale.items()
                }
            )
        )


def test_validate_sase_core_rs_requires_provider_disable_first_writer() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "provider_disable_wire_schema_version",
        "provider_disable_get",
        "provider_disable_set_relative",
        "provider_disable_set_until",
        "provider_disable_try_set_relative",
        "provider_disable_try_set_until",
        "provider_disable_clear",
    }
    assert bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )

    def first_writer_module() -> SimpleNamespace:
        state: dict[str, dict[str, object]] = {}

        def try_relative(
            _home: str,
            provider: str,
            source: str,
            mode: str = "hard",
            duration_seconds: float = 0.0,
            now: float = 0.0,
        ) -> dict[str, object]:
            return _store_if_absent(
                state,
                provider,
                source,
                mode,
                now,
                now + duration_seconds,
            )

        def try_until(
            _home: str,
            provider: str,
            expires_at: float,
            source: str,
            mode: str = "hard",
            now: float = 0.0,
        ) -> dict[str, object]:
            return _store_if_absent(state, provider, source, mode, now, expires_at)

        def get_snapshot(_home: str, _current: float) -> dict[str, object]:
            return {
                "version": 2,
                "disables": [state[name] for name in sorted(state)],
            }

        return SimpleNamespace(
            provider_disable_try_set_relative=try_relative,
            provider_disable_try_set_until=try_until,
            provider_disable_get=get_snapshot,
        )

    def _store_if_absent(
        state: dict[str, dict[str, object]],
        provider: str,
        source: str,
        mode: str,
        current: float,
        expires_at: float,
    ) -> dict[str, object]:
        existing = state.get(provider)
        existing_expires = (
            existing.get("expires_at") if isinstance(existing, dict) else None
        )
        if (
            isinstance(existing, dict)
            and isinstance(existing_expires, (int, float))
            and current < float(existing_expires)
        ):
            return {"version": 2, "inserted": False, "record": existing}
        record = {
            "version": 2,
            "provider": provider,
            "created_at": current,
            "expires_at": expires_at,
            "source": source,
            "mode": mode,
        }
        state[provider] = record
        return {"version": 2, "inserted": True, "record": record}

    assert validator._validate_provider_disable_first_writer(first_writer_module())

    def always_insert(
        _home: str,
        provider: str,
        source: str,
        mode: str = "hard",
        duration_seconds: float = 0.0,
        now: float = 0.0,
    ) -> dict[str, object]:
        return {
            "version": 2,
            "inserted": True,
            "record": {
                "version": 2,
                "provider": provider,
                "created_at": now,
                "expires_at": now + duration_seconds,
                "source": source,
                "mode": mode,
            },
        }

    stale = first_writer_module()
    stale.provider_disable_try_set_relative = always_insert
    assert not validator._validate_provider_disable_first_writer(stale)


def test_validate_sase_core_rs_requires_vcs_log_wire_schema_four() -> None:
    validator = load_validate_sase_core_rs()

    def _raise() -> int:
        raise RuntimeError("stale wheel")

    assert validator._validate_vcs_log_wire_schema(
        SimpleNamespace(vcs_log_wire_schema_version=lambda: 4)
    )
    assert not validator._validate_vcs_log_wire_schema(
        SimpleNamespace(vcs_log_wire_schema_version=lambda: 3)
    )
    assert not validator._validate_vcs_log_wire_schema(
        SimpleNamespace(vcs_log_wire_schema_version=_raise)
    )


def test_validate_sase_core_rs_requires_finalizer_schema_one() -> None:
    validator = load_validate_sase_core_rs()

    class FinalizerModule(SimpleNamespace):
        def finalizer_wire_schema_version(self) -> int:
            return 1

        def validate_finalizer_provider_spec(self, _spec: dict[str, object]) -> None:
            return None

        def validate_finalizer_instance_spec(self, _spec: dict[str, object]) -> None:
            return None

        def resolve_finalizer_plan(
            self, _plan_input: dict[str, object]
        ) -> dict[str, object]:
            return {
                "schema_version": 1,
                "entries": [
                    {
                        "instance_id": "commit",
                        "provider_ref": "builtin@commit",
                        "after": [],
                        "policy": {"max_attempts": 2, "refusal": "fail"},
                        "selector_index": 0,
                        "resolved_index": 0,
                    }
                ],
                "required": [],
                "selectors": [],
                "plan_digest": "sha256:plan",
            }

        def finalizer_plan_digest(self, _plan: dict[str, object]) -> str:
            return "sha256:plan"

        def validate_finalizer_context(
            self, _plan: dict[str, object], _context: dict[str, object]
        ) -> str:
            return "sha256:context"

        def finalizer_json_digest(self, _payload: dict[str, object]) -> str:
            return "sha256:payload"

        def validate_finalizer_submission(
            self,
            _plan: dict[str, object],
            _context: dict[str, object],
            _submission: dict[str, object],
        ) -> dict[str, object]:
            return {
                "schema_version": 1,
                "submission_digest": "sha256:submission",
                "accepted_instances": ["commit"],
            }

        def aggregate_finalizer_outcomes(
            self, _results: list[dict[str, object]]
        ) -> dict[str, object]:
            return {
                "schema_version": 1,
                "status": "success",
                "instances": [{"instance_id": "commit", "status": "success"}],
                "diagnostics": [],
            }

    assert validator._validate_finalizer_contract(FinalizerModule())

    stale = FinalizerModule()
    stale.finalizer_wire_schema_version = lambda: 2
    assert not validator._validate_finalizer_contract(stale)


def _skill_layout_payload(
    *,
    schema_version: int = 5,
    package_locator: str = "package:xprompts/skills",
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "skill_sources": [
            {
                "id": "project_skills",
                "locator": "/workspace/demo/sase/skills",
            },
            {"id": "home_skills", "locator": "/home/alice/sase/skills"},
            {
                "id": "home_project_skills",
                "locator": "/home/alice/sase/skills/demo",
            },
            {"id": "package_skills", "locator": package_locator},
        ],
    }


def test_validate_sase_core_rs_requires_singular_skill_contract() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {"skill_reference_name", "sase_content_layout"}

    def module(
        *,
        references: dict[tuple[str, str | None], str] | None = None,
        layout: object | None = None,
    ) -> SimpleNamespace:
        references = references or {
            ("foo", None): "skill/foo",
            ("foo", "app"): "app/skill/foo",
        }
        if layout is None:
            layout = _skill_layout_payload()
        return SimpleNamespace(
            skill_reference_name=lambda name, project=None: references[(name, project)],
            sase_content_layout=lambda *_args: layout,
        )

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_skill_reference_contract(module())
    assert not validator._validate_skill_reference_contract(
        module(
            references={
                ("foo", None): "skills/foo",
                ("foo", "app"): "app/skills/foo",
            }
        )
    )
    assert not validator._validate_skill_reference_contract(
        module(layout=_skill_layout_payload(schema_version=3))
    )
    assert not validator._validate_skill_reference_contract(
        module(layout=_skill_layout_payload(package_locator="package:skills"))
    )


def test_validate_sase_core_rs_requires_stats_v6_commit_and_truncation_fields() -> None:
    validator = load_validate_sase_core_rs()

    def module_with_payload(payload: object) -> SimpleNamespace:
        return SimpleNamespace(
            rebuild_agent_artifact_index=lambda *_args: {},
            agent_stats_query_runs=lambda *_args: payload,
        )

    valid_payload = {
        "schema_version": 6,
        "work": {"projects": [], "changespecs": []},  # legacy wire key
        "commits": {"committing_runs": 0, "committing_agents": 0},
        "xprompts": {
            "rows": [
                {
                    "models_truncated": 0,
                    "projects_truncated": 0,
                    "partners_truncated": 0,
                }
            ]
        },
        "runners": {
            "lanes_counted": 0,
            "lanes_without_end_skipped": 0,
            "user_hidden_skipped": 0,
        },
    }

    assert not validator._validate_agent_stats_work_schema(
        module_with_payload({"schema_version": 3})
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 3,
                "work": {"projects": [], "changespecs": []},
            }  # legacy wire key
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 4,
                "work": {"projects": [], "changespecs": []},
            }  # legacy wire key
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 5,
                "work": {"projects": [], "changespecs": []},  # legacy wire key
                "xprompts": {"rows": []},
            }
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                **valid_payload,
                "commits": {"committing_agents": 0},
            }
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                **valid_payload,
                "xprompts": {"rows": [{"models_truncated": 0}]},
            }
        )
    )
    assert validator._validate_agent_stats_work_schema(
        module_with_payload(valid_payload)
    )

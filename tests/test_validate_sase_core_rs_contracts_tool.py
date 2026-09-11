from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests._validate_sase_core_rs_tool_helpers import load_validate_sase_core_rs


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
        "artifact_ref_document_scan_wire_schema_version": 1,
        "artifact_ref_target_resolution_wire_schema_version": 1,
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


def test_validate_sase_core_rs_requires_expected_finalizer_schema() -> None:
    validator = load_validate_sase_core_rs()
    expected = validator.EXPECTED_FINALIZER_WIRE_SCHEMA_VERSION

    class FinalizerModule(SimpleNamespace):
        def finalizer_wire_schema_version(self) -> int:
            return int(expected)

        def validate_finalizer_provider_spec(self, _spec: dict[str, object]) -> None:
            return None

        def validate_finalizer_instance_spec(self, _spec: dict[str, object]) -> None:
            return None

        def resolve_finalizer_plan(
            self, _plan_input: dict[str, object]
        ) -> dict[str, object]:
            return {
                "schema_version": expected,
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

        def validate_finalizer_plan(self, plan: dict[str, object]) -> str:
            return str(plan.get("plan_digest", "sha256:plan"))

        def authenticate_finalizer_plan(
            self, plan: dict[str, object], expected_digest: str
        ) -> str:
            digest = str(plan.get("plan_digest", "sha256:plan"))
            if expected_digest != digest:
                raise ValueError("expected plan digest does not match")
            return digest

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
                "schema_version": expected,
                "submission_digest": "sha256:submission",
                "accepted_instances": ["commit"],
            }

        def aggregate_finalizer_outcomes(
            self, _results: list[dict[str, object]]
        ) -> dict[str, object]:
            return {
                "schema_version": expected,
                "status": "success",
                "instances": [{"instance_id": "commit", "status": "success"}],
                "diagnostics": [],
            }

    assert validator._validate_finalizer_contract(FinalizerModule())

    stale = FinalizerModule()
    stale.finalizer_wire_schema_version = lambda: expected - 1
    assert not validator._validate_finalizer_contract(stale)

    ahead = FinalizerModule()
    ahead.finalizer_wire_schema_version = lambda: expected + 1
    assert not validator._validate_finalizer_contract(ahead)


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

"""Tests for shared diagnostics models and registry helpers."""

from __future__ import annotations

import json

import pytest

from sase.diagnostics.models import (
    DiagnosticCheck,
    DiagnosticReport,
    aggregate_check_status,
    count_check_statuses,
    diagnostic_exit_code,
    diagnostic_report_to_dict,
    redact_string,
    redact_value,
)
from sase.diagnostics.registry import (
    CheckSpec,
    DiagnosticRegistry,
    UnknownCheckSelection,
    run_check_spec_safely,
)


def _check(
    check_id: str,
    status: str,
    *,
    group: str = "runtime",
    title: str | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=check_id,
        group=group,
        status=status,  # type: ignore[arg-type]
        title=title or check_id,
        summary=f"{check_id} summary",
    )


def test_status_aggregation_counts_and_exit_codes() -> None:
    checks = (
        _check("runtime.version", "OK"),
        _check("runtime.environment", "WARN"),
        _check("state.paths", "SKIP", group="state"),
    )

    assert aggregate_check_status(checks) == "WARN"
    assert count_check_statuses(checks) == {
        "OK": 1,
        "WARN": 1,
        "ERROR": 0,
        "SKIP": 1,
    }
    assert diagnostic_exit_code("WARN") == 0
    assert diagnostic_exit_code("WARN", strict=True) == 1
    assert diagnostic_exit_code("ERROR") == 1
    assert diagnostic_exit_code("SKIP", strict=True) == 0

    assert aggregate_check_status((*checks, _check("runtime.core", "ERROR"))) == "ERROR"


def test_all_skipped_and_empty_reports_exit_zero() -> None:
    skipped = DiagnosticReport(
        generated_at="2026-06-09T16:00:00Z",
        cwd="/workspace",
        project="sase",
        sase_home="/home/user/.sase",
        checks=(
            _check("ops.telemetry_status", "SKIP", group="ops"),
            _check("project.beads", "SKIP", group="project"),
        ),
    )

    assert skipped.status == "SKIP"
    assert skipped.exit_code(strict=True) == 0

    empty = DiagnosticReport(
        generated_at="2026-06-09T16:00:00Z",
        cwd="/workspace",
        sase_home="/home/user/.sase",
        checks=(),
    )
    assert empty.status == "SKIP"
    assert empty.exit_code() == 0


def test_json_shape_and_redaction() -> None:
    report = DiagnosticReport(
        generated_at="2026-06-09T16:00:00Z",
        cwd="/workspace",
        project="sase",
        sase_home="/home/user/.sase",
        deep=True,
        strict=True,
        selected_checks=("runtime", "plugins.doctor"),
        checks=(
            DiagnosticCheck(
                id="runtime.environment",
                group="runtime",
                status="WARN",
                title="Environment",
                summary="OPENAI_API_KEY=sk-secret123 is configured",
                details=("token=abc123",),
                next_steps=("unset SASE_TOKEN=abc123",),
                data={
                    "path": "/workspace",
                    "api_key": "sk-secret123",
                    "nested": {"telegram_token": "123456"},
                    "argv": ["--password=hunter2", "--safe=value"],
                },
                duration_ms=12,
            ),
        ),
    )

    payload = diagnostic_report_to_dict(report)
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == 1
    assert payload["command"] == "doctor"
    assert payload["status"] == "WARN"
    assert payload["generated_at"] == "2026-06-09T16:00:00Z"
    assert payload["cwd"] == "/workspace"
    assert payload["project"] == "sase"
    assert payload["sase_home"] == "/home/user/.sase"
    assert payload["deep"] is True
    assert payload["strict"] is True
    assert payload["selected_checks"] == ["runtime", "plugins.doctor"]
    assert payload["counts"] == {"OK": 0, "WARN": 1, "ERROR": 0, "SKIP": 0}
    assert payload["checks"][0]["duration_ms"] == 12
    assert payload["checks"][0]["data"]["api_key"] == "[REDACTED]"
    assert payload["checks"][0]["data"]["nested"]["telegram_token"] == "[REDACTED]"
    assert "sk-secret123" not in encoded
    assert "abc123" not in encoded
    assert "hunter2" not in encoded


def test_redaction_helpers_preserve_non_secret_structure() -> None:
    assert redact_string("Authorization: Bearer abc.def.ghi") == (
        "Authorization: Bearer [REDACTED]"
    )
    assert redact_value({"safe": ["one", 2], "password": "secret"}) == {
        "safe": ["one", 2],
        "password": "[REDACTED]",
    }


def test_registry_lists_selects_and_preserves_stable_order() -> None:
    specs = (
        CheckSpec(
            id="runtime.version",
            group="runtime",
            title="Runtime version",
            runner=lambda: _check("runtime.version", "OK"),
        ),
        CheckSpec(
            id="plugins.doctor",
            group="plugins",
            title="Plugin doctor",
            runner=lambda: _check("plugins.doctor", "OK", group="plugins"),
        ),
        CheckSpec(
            id="runtime.core_deep",
            group="runtime",
            title="Runtime deep",
            runner=lambda: _check("runtime.core_deep", "OK"),
            deep=True,
        ),
    )
    registry = DiagnosticRegistry(specs)

    assert [spec.id for spec in registry.list_default_checks()] == [
        "runtime.version",
        "plugins.doctor",
    ]
    assert [spec.id for spec in registry.list_deep_checks()] == ["runtime.core_deep"]
    assert [spec.id for spec in registry.select(("runtime",), include_deep=True)] == [
        "runtime.version",
        "runtime.core_deep",
    ]
    assert [
        spec.id
        for spec in registry.select(
            ("plugins.doctor", "runtime.version", "runtime.version")
        )
    ] == ["runtime.version", "plugins.doctor"]

    with pytest.raises(UnknownCheckSelection) as exc_info:
        registry.select(("runtime.core_deep",), include_deep=False)
    assert exc_info.value.selections == ("runtime.core_deep",)


def test_registry_run_wraps_exceptions_as_error_checks() -> None:
    def fail() -> DiagnosticCheck:
        raise RuntimeError("token=secret-token")

    spec = CheckSpec(
        id="runtime.core",
        group="runtime",
        title="Rust core health",
        runner=fail,
    )

    checks = run_check_spec_safely(spec)

    assert len(checks) == 1
    assert checks[0].id == "runtime.core"
    assert checks[0].group == "runtime"
    assert checks[0].status == "ERROR"
    assert "failed unexpectedly" in checks[0].summary
    assert "secret-token" not in checks[0].details[0]


def test_registry_run_returns_selected_checks_in_order() -> None:
    registry = DiagnosticRegistry(
        (
            CheckSpec(
                id="runtime.version",
                group="runtime",
                title="Runtime version",
                runner=lambda: _check("runtime.version", "OK"),
            ),
            CheckSpec(
                id="state.paths",
                group="state",
                title="State paths",
                runner=lambda: (
                    _check("state.paths", "WARN", group="state"),
                    _check("state.paths.detail", "OK", group="state"),
                ),
            ),
        )
    )

    checks = registry.run(("state",))

    assert [check.id for check in checks] == ["state.paths", "state.paths.detail"]
    assert checks[0].duration_ms >= 0

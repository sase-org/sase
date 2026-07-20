"""Facade and CLI coverage for strict plan validation."""

from __future__ import annotations

import argparse
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main import plan_command_handler
from sase.main.parser import create_parser
from sase.main.plan_validate_handler import handle_plan_validate_command
from sase.sdd.plan_validate import (
    PlanDiagnosticSeverity,
    plan_frontmatter_schema,
    validate_plan,
    validate_plan_file,
)


VALID_TALE = """---
tier: tale
title: Strict plan validation
goal: Ship strict plan validation
---
# Plan

Implement it.
"""

VALID_EPIC = """---
tier: epic
title: Strict plan validation
goal: Plans are validated before execution
parent_bead: sase-parent.2
phases:
  - id: core
    title: Core validator
    depends_on: []
    description: "'Core validator' section: build the shared validation engine."
    size: medium
  - id: cli
    title: CLI integration
    depends_on: [core]
    description: "'CLI integration' section: wire the validator into the command."
    size: large
---
# Plan

Implement it.
"""


def _parse(argv: list[str]) -> argparse.Namespace:
    return create_parser().parse_args(argv)


def _invoke(argv: list[str]) -> int:
    args = _parse(["plan", "validate", *argv])
    with pytest.raises(SystemExit) as excinfo:
        handle_plan_validate_command(args)
    return int(excinfo.value.code)


def test_facade_rehydrates_valid_tale_and_ordered_schema() -> None:
    result = validate_plan(VALID_TALE, "tale")

    assert result.ok
    assert result.schema_version == 2
    assert result.diagnostics == ()
    assert result.plan is not None
    assert result.plan.tier == "tale"
    assert result.plan.goal == "Ship strict plan validation"
    assert result.plan.title == "Strict plan validation"
    assert result.plan.phases == ()
    assert [field.name for field in plan_frontmatter_schema("tale")] == [
        "tier",
        "title",
        "goal",
        "model",
        "create_time",
        "status",
        "prompt",
        "bead_id",
    ]


def test_facade_rehydrates_normalized_epic_phases() -> None:
    descriptionless_epic = VALID_EPIC.replace(
        "    description: \"'CLI integration' section: wire the validator into the command.\"\n",
        "",
    )
    result = validate_plan(descriptionless_epic, "epic")

    assert result.ok
    assert result.plan is not None
    assert result.plan.title == "Strict plan validation"
    assert result.plan.parent_bead == "sase-parent.2"
    assert [phase.id for phase in result.plan.phases] == ["core", "cli"]
    assert [phase.size for phase in result.plan.phases] == ["medium", "large"]
    assert result.plan.phases[1].depends_on == ("core",)
    assert result.plan.phases[1].description is None


def test_file_facade_supports_authoring_and_legacy_launch_modes(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy.md"
    legacy.write_text(
        VALID_EPIC.replace("    size: medium\n", "").replace("    size: large\n", ""),
        encoding="utf-8",
    )

    authoring = validate_plan_file(legacy, "epic")
    launch = validate_plan_file(legacy, "epic", mode="launch")

    assert not authoring.ok
    assert [diagnostic.code for diagnostic in authoring.diagnostics] == [
        "phase-size-missing",
        "phase-size-missing",
    ]
    assert launch.ok
    assert [diagnostic.severity for diagnostic in launch.diagnostics] == [
        PlanDiagnosticSeverity.WARNING,
        PlanDiagnosticSeverity.WARNING,
    ]
    assert launch.plan is not None
    assert [phase.size for phase in launch.plan.phases] == ["small", "small"]


def test_facade_rehydrates_all_diagnostics_and_is_frozen() -> None:
    result = validate_plan(
        """---
tier: epic
title: Diagnostic aggregation
goal: '   '
tyop: value
---
# Plan
""",
        "tale",
    )

    assert not result.ok
    assert result.plan is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unknown-key",
        "tier-mismatch",
        "value-empty",
    ]
    assert result.diagnostics[0].line == 5
    assert result.diagnostics[0].severity is PlanDiagnosticSeverity.ERROR
    with pytest.raises(FrozenInstanceError):
        result.diagnostics[0].code = "changed"  # type: ignore[misc]


def test_facade_rejects_unknown_wire_schema_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.sdd.plan_validate.require_rust_binding",
        lambda _name: (
            lambda _content, _tier, _mode: {
                "schema_version": 999,
                "ok": True,
                "diagnostics": [],
                "plan": None,
            }
        ),
    )

    with pytest.raises(ValueError, match="wire schema version 999"):
        validate_plan(VALID_TALE, "tale")


def test_parser_requires_explicit_tier(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _parse(["plan", "validate", "plan.md"])

    assert excinfo.value.code == 2
    assert "--tier" in capsys.readouterr().err


def test_parser_accepts_all_validate_options() -> None:
    args = _parse(
        ["plan", "validate", "plan.md", "--json", "--quiet", "--tier", "epic"]
    )

    assert args.plan_subcommand == "validate"
    assert args.plan_file == "plan.md"
    assert args.json is True
    assert args.quiet is True
    assert args.tier == "epic"


def test_plan_command_dispatches_validate() -> None:
    args = argparse.Namespace(plan_subcommand="validate")

    with (
        patch.object(
            plan_command_handler,
            "handle_plan_validate_command",
            side_effect=SystemExit(1),
        ) as validate_mock,
        pytest.raises(SystemExit) as excinfo,
    ):
        plan_command_handler.handle_plan_command(args)

    assert excinfo.value.code == 1
    validate_mock.assert_called_once_with(args)


def test_valid_human_output_and_quiet_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "tale.md"
    plan.write_text(VALID_TALE, encoding="utf-8")

    assert _invoke([str(plan), "-t", "tale"]) == 0
    captured = capsys.readouterr()
    assert "Validation passed" in captured.out
    assert "valid tale plan" in captured.out
    assert captured.err == ""

    assert _invoke([str(plan), "-t", "tale", "--quiet"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_valid_epic_and_json_quiet_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "epic.md"
    plan.write_text(VALID_EPIC, encoding="utf-8")

    assert _invoke([str(plan), "-t", "epic", "--json", "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["tier"] == "epic"
    assert payload["diagnostics"] == []


def test_epic_failure_renders_size_parent_schema_and_minimal_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "epic.md"
    plan.write_text(
        VALID_EPIC.replace("    size: medium", "    size: enormous"),
        encoding="utf-8",
    )

    assert _invoke([str(plan), "-t", "epic", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    fields = {field["name"]: field for field in payload["expected_schema"]["fields"]}
    assert fields["phases[].size"]["type"] == "small | medium | large"
    assert fields["phases[].size"]["required"] is True
    assert fields["phases[].size"]["example"] == "small"
    assert fields["parent_bead"]["required"] is False
    assert fields["parent_bead"]["example"] == "sase-7z.1"
    assert "  size: small" in payload["expected_schema"]["example"]


def test_failure_human_output_is_location_bearing_and_self_teaching(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "mismatch.md"
    plan.write_text(VALID_EPIC, encoding="utf-8")

    assert _invoke([str(plan), "-t", "tale"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{plan}:2: error [tier-mismatch]" in captured.err
    assert "Expected tale frontmatter schema" in captured.err
    assert "Minimal valid tale plan" in captured.err
    assert "title: Ship the requested capability" in captured.err
    assert "goal: The requested capability works end to end." in captured.err
    assert "Validation failed" in captured.err


def test_failure_json_envelope_has_core_parity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "mismatch.md"
    plan.write_text(VALID_EPIC, encoding="utf-8")

    assert _invoke([str(plan), "-t", "tale", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert set(payload) == {
        "schema_version",
        "ok",
        "tier",
        "path",
        "diagnostics",
        "expected_schema",
    }
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["path"] == str(plan)
    mismatch = next(
        diagnostic
        for diagnostic in payload["diagnostics"]
        if diagnostic["code"] == "tier-mismatch"
    )
    assert mismatch == {
        "severity": "error",
        "code": "tier-mismatch",
        "field_path": "tier",
        "message": "authored tier `epic` does not match requested tier `tale`",
        "line": 2,
    }
    assert payload["expected_schema"]["fields"][0]["type"] == "tale | epic"
    assert "field_type" not in payload["expected_schema"]["fields"][0]
    assert payload["expected_schema"]["example"].startswith("---\ntier: tale")
    assert (
        "title: Ship the requested capability" in payload["expected_schema"]["example"]
    )


@pytest.mark.parametrize("tier", ["tale", "epic"])
@pytest.mark.parametrize(
    ("title_line", "expected_code"),
    [
        ("", "required-missing"),
        ("title: '   '\n", "value-empty"),
        ("title: [not, text]\n", "type-mismatch"),
    ],
)
def test_cli_rejects_missing_blank_and_wrong_typed_titles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tier: str,
    title_line: str,
    expected_code: str,
) -> None:
    extra = (
        "phases:\n  - id: core\n    title: Core\n    depends_on: []\n"
        "    description: Core section exercises title validation.\n"
        "    size: small\n"
        if tier == "epic"
        else ""
    )
    plan = tmp_path / f"{tier}.md"
    plan.write_text(
        f"---\ntier: {tier}\n{title_line}goal: outcome\n{extra}---\nbody\n",
        encoding="utf-8",
    )

    assert _invoke([str(plan), "-t", tier, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    title_diagnostics = [
        diagnostic
        for diagnostic in payload["diagnostics"]
        if diagnostic["field_path"] == "title"
    ]
    assert [diagnostic["code"] for diagnostic in title_diagnostics] == [expected_code]
    assert title_diagnostics[0]["line"] is not None


@pytest.mark.parametrize(
    ("tier", "content", "expected_codes", "expected_exit"),
    [
        ("tale", "# Plan\n", {"frontmatter-missing"}, 1),
        ("tale", "---\ntier: tale\n", {"frontmatter-unclosed"}, 1),
        (
            "tale",
            "---\ntier: [tale\n---\n",
            {"body-empty", "yaml-invalid"},
            1,
        ),
        (
            "tale",
            "---\n- tale\n---\nbody\n",
            {"frontmatter-not-mapping"},
            1,
        ),
        (
            "tale",
            "---\ntier: tale\ngoal: x\n---\n",
            {"body-empty"},
            1,
        ),
        (
            "tale",
            """---
tier: epic
goal: '   '
model: |
  bad
  model
tyop: value
---
body
""",
            {"unknown-key", "tier-mismatch", "value-empty", "model-invalid"},
            1,
        ),
        (
            "tale",
            "---\ntier: story\ngoal: [not, text]\n---\nbody\n",
            {"tier-invalid", "type-mismatch"},
            1,
        ),
        (
            "tale",
            """---
tier: tale
goal: Small outcome
title: Ignored
phases: nonsense
changespec: ''
bug_id: nope
---
body
""",
            {"tale-inert-field"},
            0,
        ),
        (
            "epic",
            """---
tier: epic
goal: outcome
title: 42
changespec: ''
bug_id: nope
phases: []
---
body
""",
            {
                "type-mismatch",
                "value-empty",
                "bug-id-without-changespec",
                "phases-empty",
            },
            1,
        ),
        (
            "epic",
            """---
tier: epic
goal: outcome
title: title
phases:
  - nope
  - id: core
    surprise: true
    description: Core section exercises malformed phase fields.
---
body
""",
            {"phase-type-mismatch", "unknown-key", "required-missing"},
            1,
        ),
        (
            "epic",
            """---
tier: epic
goal: outcome
title: title
phases:
  - id: Bad slug
    title: First
    depends_on: [Bad slug, future, missing, missing]
    description: First section exercises invalid dependencies.
  - id: future
    title: Future
    depends_on: []
    description: Future section exercises forward references.
  - id: future
    title: Duplicate
    depends_on: nope
    description: Duplicate section exercises duplicate ids.
---
body
""",
            {
                "phase-id-invalid",
                "phase-id-duplicate",
                "dep-self",
                "dep-forward",
                "dep-unknown",
                "dep-duplicate",
                "type-mismatch",
            },
            1,
        ),
    ],
)
def test_cli_passes_through_every_core_diagnostic_family(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tier: str,
    content: str,
    expected_codes: set[str],
    expected_exit: int,
) -> None:
    plan = tmp_path / "diagnostics.md"
    plan.write_text(content, encoding="utf-8")

    assert _invoke([str(plan), "-t", tier]) == expected_exit
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    for code in expected_codes:
        assert f"[{code}]" in rendered
    if expected_exit:
        assert f"Expected {tier} frontmatter schema" in rendered
    else:
        assert "Expected tale frontmatter schema" not in rendered


def test_missing_and_non_utf8_files_are_validation_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.md"
    assert _invoke([str(missing), "-t", "tale", "--json"]) == 1
    missing_payload = json.loads(capsys.readouterr().out)
    assert missing_payload["diagnostics"][0]["code"] == "file-unreadable"

    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"first line\n\xff")
    assert _invoke([str(invalid), "-t", "tale"]) == 1
    captured = capsys.readouterr()
    assert f"{invalid}:2: error [utf8-invalid]" in captured.err

"""Diagnostic and malformed-input CLI coverage for strict plan validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.main.plan_explain import (
    EPIC_PLAN_EXPLANATION,
    INVALID_PLAN_TIER_HINT,
    TALE_PLAN_EXPLANATION,
)
from sase.main.plan_validate_handler import handle_plan_validate_command
from tests.main.parser_cli_helpers import parse_sase_args


def _parse(argv: list[str]) -> argparse.Namespace:
    return parse_sase_args(argv)


def _invoke(argv: list[str]) -> int:
    args = _parse(["plan", "validate", *argv])
    with pytest.raises(SystemExit) as excinfo:
        handle_plan_validate_command(args)
    return int(excinfo.value.code)


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

    assert _invoke([str(plan), "--json"]) == 1
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
            "epic",
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
            {"unknown-key", "value-empty", "model-invalid"},
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
changespec: ''  # legacy frontmatter key
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
changespec: ''  # legacy frontmatter key
bug_id: nope
phases: []
---
body
""",
            {
                "type-mismatch",
                "value-empty",
                "bug-id-without-patch",
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

    assert _invoke([str(plan)]) == expected_exit
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
    assert _invoke([str(missing), "--json"]) == 1
    captured = capsys.readouterr()
    missing_payload = json.loads(captured.out)
    assert missing_payload["diagnostics"][0]["code"] == "file-unreadable"
    assert INVALID_PLAN_TIER_HINT not in captured.err

    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"first line\n\xff")
    assert _invoke([str(invalid)]) == 1
    captured = capsys.readouterr()
    assert f"{invalid}:2: error [utf8-invalid]" in captured.err
    assert INVALID_PLAN_TIER_HINT not in captured.err


@pytest.mark.parametrize(
    ("tier_line", "expected_code"),
    [
        ("", "required-missing"),
        ("tier: story\n", "tier-invalid"),
    ],
)
def test_missing_or_invalid_authored_tier_has_actionable_hint_and_no_explanation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tier_line: str,
    expected_code: str,
) -> None:
    plan = tmp_path / "invalid-tier.md"
    plan.write_text(
        f"---\n{tier_line}title: Invalid tier\ngoal: Add a valid tier\n---\nbody\n",
        encoding="utf-8",
    )

    assert _invoke([str(plan), "--explain"]) == 1
    captured = capsys.readouterr()
    assert f"[{expected_code}]" in captured.err
    assert INVALID_PLAN_TIER_HINT in captured.err
    assert TALE_PLAN_EXPLANATION not in captured.err
    assert EPIC_PLAN_EXPLANATION not in captured.err

    assert _invoke([str(plan), "--json", "--explain"]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "explanation" not in payload
    assert INVALID_PLAN_TIER_HINT in captured.err

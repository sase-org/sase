"""Tests for :mod:`sase.main.plan_show_handler`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.main.plan_show_handler import handle_plan_show_command
from tests.main.parser_cli_helpers import parse_sase_args
from sase.plan_show.model import (
    PlanShowAmbiguity,
    PlanShowAmbiguityCandidate,
    PlanShowMiss,
    PlanShowPlan,
    PlanShowProposal,
    PlanShowRecord,
    PlanShowTarget,
    PlanShowValidation,
)

_PLAN_TEXT = (
    "---\ntier: tale\ntitle: A flexible plan\ngoal: G\nstatus: wip\n---\n"
    "# Heading\n\nBody text.\n"
)


def _plan(path: Path, **overrides: object) -> PlanShowPlan:
    defaults: dict[str, object] = {
        "reference": "plan:202608/a.md",
        "path": str(path),
        "relpath": "202608/a.md",
        "source": "repo",
        "exists": True,
        "tier": "tale",
        "status": "wip",
        "title": "A flexible plan",
        "goal": "G",
        "created_at": "2026-08-06",
        "frontmatter": {},
        "body": "# Heading\n\nBody text.\n",
        "validation": PlanShowValidation(ok=True, diagnostics=()),
        "provenance": (),
        "phases": (),
        "waves": None,
    }
    defaults.update(overrides)
    return PlanShowPlan(**defaults)  # type: ignore[arg-type]


def _record(path: Path, **overrides: object) -> PlanShowRecord:
    plan = overrides.pop("plan", None) or _plan(path)
    target = overrides.pop("target", None) or PlanShowTarget(
        raw="a", kind="path", status="exact"
    )
    proposal = overrides.pop("proposal", None)
    bead = overrides.pop("bead", None)
    assert not overrides
    return PlanShowRecord(target=target, plan=plan, proposal=proposal, bead=bead)  # type: ignore[arg-type]


def _args(target: str = "a", **cli_overrides: str) -> argparse.Namespace:
    argv = ["plan", "show", target]
    for flag, value in cli_overrides.items():
        argv.extend([f"--{flag}", value])
    return parse_sase_args(argv)


def _stub(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    monkeypatch.setattr(
        "sase.main.plan_show_handler.resolve_plan_show_target",
        lambda *_args, **_kwargs: result,
    )


def test_valid_plan_exits_zero_and_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "a.md"
    plan_path.write_text(_PLAN_TEXT, encoding="utf-8")
    _stub(monkeypatch, _record(plan_path))

    exit_code = handle_plan_show_command(_args(color="never"))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "A flexible plan" in out


def test_invalid_plan_still_renders_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "a.md"
    plan_path.write_text(_PLAN_TEXT, encoding="utf-8")
    _stub(
        monkeypatch,
        _record(
            plan_path,
            plan=_plan(
                plan_path,
                validation=PlanShowValidation(ok=False, diagnostics=("bad thing",)),
            ),
        ),
    )

    exit_code = handle_plan_show_command(_args(color="never"))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "bad thing" in out


def test_miss_exits_one_and_writes_only_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, PlanShowMiss(target="foo", suggestions=("plan:202608/a.md",)))

    exit_code = handle_plan_show_command(_args("foo"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "unknown plan: foo" in captured.err


def test_ambiguity_exits_one_and_writes_only_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ambiguity = PlanShowAmbiguity(
        target="a",
        candidates=(
            PlanShowAmbiguityCandidate(
                reference="plan:202607/a.md", tier="tale", created_at=None, title="A"
            ),
            PlanShowAmbiguityCandidate(
                reference="plan:202608/a.md", tier="tale", created_at=None, title="A2"
            ),
        ),
    )
    _stub(monkeypatch, ambiguity)

    exit_code = handle_plan_show_command(_args("a"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "ambiguous plan: a" in captured.err


def test_unreadable_file_exits_one_for_raw_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_path = tmp_path / "missing.md"
    _stub(monkeypatch, _record(missing_path))

    exit_code = handle_plan_show_command(_args("a", format="raw"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Error:" in captured.err


def test_json_envelope_has_schema_version_and_full_key_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "a.md"
    plan_path.write_text(_PLAN_TEXT, encoding="utf-8")
    _stub(monkeypatch, _record(plan_path))

    exit_code = handle_plan_show_command(_args("a", format="json"))

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert exit_code == 0
    assert payload["schema_version"] == 1
    assert set(payload) == {"schema_version", "target", "plan", "proposal", "bead"}
    assert payload["proposal"] is None
    assert payload["bead"] is None
    assert set(payload["plan"]) == {
        "reference",
        "path",
        "relpath",
        "source",
        "exists",
        "tier",
        "status",
        "title",
        "goal",
        "created_at",
        "frontmatter",
        "body",
        "validation",
        "provenance",
        "phases",
        "waves",
    }


def test_json_envelope_includes_proposal_and_bead_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "a.md"
    plan_path.write_text(_PLAN_TEXT, encoding="utf-8")
    _stub(
        monkeypatch,
        _record(
            plan_path,
            proposal=PlanShowProposal(
                id="abcdef120001",
                id_prefix="abcdef12",
                agent="planner",
                project="sase",
                provider_model="claude",
                age="3m",
                response_dir="~/x",
            ),
            bead="sase-64",
        ),
    )

    exit_code = handle_plan_show_command(_args("a", format="json"))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["proposal"]["id_prefix"] == "abcdef12"
    assert payload["bead"] == "sase-64"


def test_raw_format_reproduces_file_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "a.md"
    plan_path.write_text(_PLAN_TEXT, encoding="utf-8")
    _stub(monkeypatch, _record(plan_path))

    exit_code = handle_plan_show_command(_args("a", format="raw"))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert out == _PLAN_TEXT


def test_compact_format_renders_one_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "a.md"
    plan_path.write_text(_PLAN_TEXT, encoding="utf-8")
    _stub(monkeypatch, _record(plan_path))

    exit_code = handle_plan_show_command(_args("a", format="compact", color="never"))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "A flexible plan" in out
    assert out.count("\n") == 1

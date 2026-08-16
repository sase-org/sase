"""Tests for the ``sase doctor`` command shell."""

from __future__ import annotations

import argparse
import json

from sase.diagnostics import (
    CheckSpec,
    DiagnosticCheck,
    DiagnosticRegistry,
    DiagnosticReport,
)
from sase.doctor.runner import DoctorContext, build_doctor_registry
from sase.main import doctor_handler
from sase.main.parser import create_parser
from tests._project_display_case import ProjectDisplayCase


def _report(status: str = "OK", *, strict: bool = False) -> DiagnosticReport:
    return DiagnosticReport(
        generated_at="2026-06-09T16:00:00Z",
        cwd="/workspace",
        project="sase",
        sase_home="/home/user/.sase",
        strict=strict,
        checks=(
            DiagnosticCheck(
                id="runtime.version",
                group="runtime",
                status=status,  # type: ignore[arg-type]
                title="Runtime version",
                summary="runtime checked",
            ),
        ),
    )


def test_parser_accepts_doctor_flags_and_help_is_sorted() -> None:
    parser = create_parser()

    args = parser.parse_args(
        [
            "doctor",
            "-j",
            "-v",
            "-D",
            "-s",
            "-L",
            "-F",
            "-C",
            "runtime",
            "-C",
            "config.sdd",
            "-p",
            "sase",
            "-y",
        ]
    )

    assert args.command == "doctor"
    assert args.json is True
    assert args.verbose is True
    assert args.deep is True
    assert args.strict is True
    assert args.list_checks is True
    assert args.fix_duplicate_blocks is True
    assert args.check == ["runtime", "config.sdd"]
    assert args.project == "sase"
    assert args.yes is True

    subparser_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    commands = list(subparser_action.choices)
    assert "doctor" in commands
    assert commands == sorted(commands)

    help_text = subparser_action.choices["doctor"].format_help()
    assert "-j, --json" in help_text
    assert "-v, --verbose" in help_text
    assert "-D, --deep" in help_text
    assert "-F, --fix-duplicate-blocks" in help_text
    assert "-s, --strict" in help_text
    assert "-L, --list-checks" in help_text
    assert "-C, --check ID_OR_GROUP" in help_text
    assert "-p, --project PROJECT" in help_text
    assert "-y, --yes" in help_text
    assert "sase doctor -D -j" in help_text
    assert "sase doctor -F" in help_text
    assert "OK, WARN, and SKIP exit 0" in help_text


def test_doctor_json_output_returns_report_exit_code(monkeypatch, capsys) -> None:
    def fake_run_doctor(**kwargs: object) -> DiagnosticReport:
        assert kwargs["selections"] == ("runtime",)
        assert kwargs["deep"] is False
        assert kwargs["strict"] is False
        return _report("WARN")

    monkeypatch.setattr(doctor_handler, "run_doctor", fake_run_doctor)
    args = create_parser().parse_args(["doctor", "-j", "-C", "runtime"])

    exit_code = doctor_handler.handle_doctor_command(args)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "doctor"
    assert payload["status"] == "WARN"
    assert payload["checks"][0]["id"] == "runtime.version"


def test_doctor_humanizes_project_only_in_human_report(
    monkeypatch,
    capsys,
    project_display_case: ProjectDisplayCase,
) -> None:
    canonical = project_display_case.project_key
    report = DiagnosticReport(
        generated_at="2026-07-20T12:00:00Z",
        cwd="/workspace",
        project=canonical,
        sase_home="/home/user/.sase",
        checks=(
            DiagnosticCheck(
                id="project.current",
                group="project",
                status="OK",
                title="Current project",
                summary=f"{canonical}: state=enabled; launchable; 0 active claim(s)",
                data={"project_name": canonical},
            ),
        ),
    )
    monkeypatch.setattr(doctor_handler, "run_doctor", lambda **_kwargs: report)
    monkeypatch.setattr(
        "sase.project_display_names.load_project_display_snapshot",
        lambda: project_display_case.snapshot,
    )

    human_args = create_parser().parse_args(["doctor"])
    assert doctor_handler.handle_doctor_command(human_args) == 0
    human = capsys.readouterr().out
    assert project_display_case.project_label in human
    assert canonical not in human

    json_args = create_parser().parse_args(["doctor", "--json"])
    assert doctor_handler.handle_doctor_command(json_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project"] == canonical
    assert payload["checks"][0]["summary"].startswith(canonical)
    assert payload["checks"][0]["data"]["project_name"] == canonical


def test_doctor_strict_warning_exits_nonzero(monkeypatch, capsys) -> None:
    def fake_run_doctor(**kwargs: object) -> DiagnosticReport:
        return _report("WARN", strict=bool(kwargs["strict"]))

    monkeypatch.setattr(doctor_handler, "run_doctor", fake_run_doctor)
    args = create_parser().parse_args(["doctor", "-j", "-s"])

    exit_code = doctor_handler.handle_doctor_command(args)

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["strict"] is True


def test_doctor_list_checks_outputs_registered_ids(monkeypatch, capsys) -> None:
    registry = DiagnosticRegistry(
        (
            CheckSpec(
                id="runtime.version",
                group="runtime",
                title="Runtime version",
                runner=lambda: DiagnosticCheck(
                    id="runtime.version",
                    group="runtime",
                    status="OK",
                    title="Runtime version",
                    summary="ok",
                ),
            ),
        )
    )
    monkeypatch.setattr(
        doctor_handler, "build_doctor_registry", lambda _context: registry
    )
    args = create_parser().parse_args(["doctor", "-L"])

    exit_code = doctor_handler.handle_doctor_command(args)

    assert exit_code == 0
    assert (
        "runtime.version\truntime\tdefault\tRuntime version" in capsys.readouterr().out
    )


def test_doctor_registry_includes_phase4_catalog_checks(tmp_path) -> None:
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    registry = build_doctor_registry(context)

    ids = {spec.id for spec in registry.list_default_checks()}
    deep_ids = {spec.id for spec in registry.list_deep_checks()}

    assert {
        "llm.registry",
        "llm.default",
        "runtime.node",
        "install.management",
        "plugins.resources",
        "resources.disk_free",
        "plugins.github",
        "axe.chops",
        "axe.health",
        "axe.external_mirror",
        "project.duplicate_patch_blocks",
        "project.current",
        "workspace.registry",
        "state.agent_index",
        "state.agent_publication_outbox",
        "project.beads",
        "flags.registry",
        "flags.overrides",
        "flags.due",
        "ops.telemetry_status",
        "integrations.mobile_push_config",
        "tools.editor",
        "tools.tmux",
        "tools.clipboard",
        "tools.fzf",
    } <= ids
    assert {
        "config.skills.applied",
        "resources.chezmoi",
        "resources.ulimits",
        "resources.inotify",
        "state.agent_index_verify",
        "ops.telemetry_health",
        "ops.axe",
        "providers.cli_version",
        "tools.xprompt_lsp",
        "terminal.kitty_graphics",
        "tools.tmux_version",
        "terminal.truecolor",
        "tools.optional",
    } <= deep_ids


def test_doctor_deep_only_selection_suggests_deep_flag(capsys) -> None:
    """Selecting a deep-only check without -D names the fix, not "unknown".

    ``sase doctor -L`` lists deep checks, so rejecting an explicit selection
    of one as "unknown diagnostic check or group" was factually wrong.
    """
    args = create_parser().parse_args(["doctor", "-C", "tools.optional"])

    exit_code = doctor_handler.handle_doctor_command(args)

    err = capsys.readouterr().err
    assert exit_code == 2
    assert "tools.optional" in err
    assert "-D/--deep" in err
    assert "unknown diagnostic check" not in err


def test_doctor_mixed_unknown_and_deep_only_selection_reports_both(capsys) -> None:
    """A deep-only hint must not hide a genuinely unknown selection."""
    args = create_parser().parse_args(
        ["doctor", "-C", "bogus.check", "-C", "tools.optional"]
    )

    exit_code = doctor_handler.handle_doctor_command(args)

    err = capsys.readouterr().err
    assert exit_code == 2
    assert "unknown diagnostic check or group: bogus.check" in err
    assert "tools.optional selects deep checks only" in err
    assert "-D/--deep" in err

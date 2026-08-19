"""End-to-end proofs for plugin-extensible task bead types."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.widgets.artifacts.beads_rendering import task_text
from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.bead_pages.rendering_identity import render_prose_sections
from sase.config.layers import ConfigLayer
from sase.doctor.checks_beads import _check_task_types
from sase.doctor.checks_plugins import _check_plugins_required
from sase.doctor.runner import DoctorContext
from sase.main.parser import create_parser
from sase.task_type_presentation import task_type_chip, task_type_cli_cell
from sase.main.init_memory.root_rendering import render_generated_task_types_memory_body
from sase.task_types import (
    TaskTypeCreateError,
    assemble_task_type_registry,
    build_committed_task_type_snapshot_entries,
    hookimpl,
    render_task_type_snapshot_json,
    reset_task_type_registry_cache,
    resolve_created_task_type,
)
from sase.task_types._models import TaskTypeDiagnostic, TaskTypeRegistry
from sase.task_types.registry import TASK_TYPE_ENTRY_POINT_GROUP
from tests.main.parser_cli_helpers import parse_sase_args


def _create_flake(
    *,
    evidence_path: Path | None = None,
    extra: list[str] | None = None,
) -> None:
    argv = [
        "bead",
        "create",
        "--title",
        "Flaky retry",
        "--type",
        "task(flake)",
        "--size",
        "medium",
        "--description",
        "Found while landing the retry patch.",
        "--field",
        "node_id=tests/foo.py::test_bar",
    ]
    if evidence_path is not None:
        argv.extend(["--field", f"evidence=@{evidence_path}"])
    else:
        argv.extend(["--field", "evidence=failed then passed"])
    if extra:
        argv.extend(extra)
    bead_cli.handle_bead_create(create_parser().parse_args(argv))


def test_typed_task_round_trip_renders_body_and_chips(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("failed then passed on the same tree\n", encoding="utf-8")
    _create_flake(evidence_path=evidence)
    capsys.readouterr()

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.task_type == "flake"
    assert task.task_type_fields["node_id"] == "tests/foo.py::test_bar"
    assert task.task_type_fields["evidence"] == "failed then passed on the same tree\n"
    assert "Flake report" not in task.description

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", task.id]))
    shown = capsys.readouterr().out
    assert "Found while landing the retry patch." in shown
    assert shown.index("Found while landing the retry patch.") < shown.index(
        "## Flake report"
    )
    assert "`tests/foo.py::test_bar`" in shown
    assert "failed then passed on the same tree" in shown

    bead_cli.handle_bead_list(
        parse_sase_args(["bead", "list", "--format", "json", "--task-type", "flake"])
    )
    listed = json.loads(capsys.readouterr().out)
    assert [row["title"] for row in listed["results"]] == ["Flaky retry"]
    assert listed["results"][0]["task_type"] == "flake"

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))
    compact = capsys.readouterr().out
    assert "≈" in compact
    assert task.id in compact
    assert task_type_cli_cell("flake", use_color=False) == "≈"

    ace_row = task_text(task, triage=False, plan_link=False)
    assert "≈" in ace_row.plain
    assert task.id in ace_row.plain
    assert "flake" in task_type_chip("flake").plain

    page = "\n".join(render_prose_sections(task))
    assert page.index("Found while landing the retry patch.") < page.index(
        "Flake report"
    )


def test_project_config_use_override_changes_only_declared_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.config.layers import ConfigLayer

    layer = ConfigLayer(
        name="local",
        path=None,
        exists=True,
        list_strategy="concatenate",
        data={
            "bead": {
                "task_types": [
                    {
                        "use": "builtin@bug",
                        "label": "Project bug",
                        "triage": {"min_plus_ones": 3},
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", lambda: []
    )
    baseline = assemble_task_type_registry(entry_points_fn=lambda **_: [])
    builtin_summary = baseline.by_slug["bug"].spec["summary"]
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", lambda: [layer]
    )
    registry = assemble_task_type_registry(entry_points_fn=lambda **_: [])
    record = registry.by_slug["bug"]
    assert record.spec["label"] == "Project bug"
    assert record.spec["triage"]["min_plus_ones"] == 3
    assert record.spec["summary"] == builtin_summary
    assert record.provenance.source == "project"


def test_missing_plugin_type_degrades_on_read_and_names_install_on_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = Issue(
        id="task-1",
        title="Mirrored",
        issue_type=IssueType.TASK,
        task_type="github",
        task_type_fields={"external": "sase-org/sase#1"},
    )
    from sase.task_types import render_task_type_display_block

    rendered = render_task_type_display_block(
        issue, registry=TaskTypeRegistry(records=(), diagnostics=())
    )
    assert "Task type: github (not installed on this machine)" in rendered
    assert "**external:** sase-org/sase#1" in rendered

    monkeypatch.setattr(
        "sase.task_types.fields._snapshot_entry",
        lambda slug: (
            {"task_type": slug, "package": "sase-github"} if slug == "github" else None
        ),
    )
    empty = TaskTypeRegistry(records=(), diagnostics=())
    with pytest.raises(TaskTypeCreateError, match="sase plugin install sase-github"):
        resolve_created_task_type("github", {}, registry=empty)


def test_optional_plugin_types_do_not_change_generated_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Plugin:
        @hookimpl
        def task_type_specs(self) -> tuple[dict[str, Any], ...]:
            return (
                {
                    "schema_version": 1,
                    "task_type": "incident",
                    "label": "Incident",
                    "summary": "An optional plugin type.",
                    "when_to_use": "Agents never see this in generated memory.",
                },
            )

    class _Dist:
        name = "sase-linear"
        version = "0.3.0"

        @property
        def metadata(self) -> dict[str, str]:
            return {"Name": self.name, "Version": self.version}

    class _EntryPoint:
        name = "linear"
        group = TASK_TYPE_ENTRY_POINT_GROUP
        dist = _Dist()

        def load(self) -> object:
            return Plugin()

    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", lambda: []
    )
    reset_task_type_registry_cache()
    with_optional = assemble_task_type_registry(
        entry_points_fn=lambda **_: [_EntryPoint()]
    )
    without_optional = assemble_task_type_registry(entry_points_fn=lambda **_: [])
    assert "incident" in with_optional.by_slug
    assert "incident" not in without_optional.by_slug

    monkeypatch.setattr(
        "sase.task_types.snapshot._project_required_plugin_packages",
        lambda: frozenset(),
    )
    with_entries = build_committed_task_type_snapshot_entries(with_optional)
    without_entries = build_committed_task_type_snapshot_entries(without_optional)
    assert [entry["task_type"] for entry in with_entries] == [
        entry["task_type"] for entry in without_entries
    ]
    assert render_task_type_snapshot_json(
        with_entries
    ) == render_task_type_snapshot_json(without_entries)

    monkeypatch.setattr(
        "sase.main.init_memory.root_rendering.get_task_type_registry",
        lambda: with_optional,
    )
    with_note, with_error = render_generated_task_types_memory_body(
        include_project_memory=True
    )
    monkeypatch.setattr(
        "sase.main.init_memory.root_rendering.get_task_type_registry",
        lambda: without_optional,
    )
    without_note, without_error = render_generated_task_types_memory_body(
        include_project_memory=True
    )
    assert with_error is None and without_error is None
    assert with_note == without_note
    assert with_note is not None
    assert "incident" not in with_note


def test_home_task_type_note_omits_a_machine_global_disabled_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_layer = ConfigLayer(
        name="user",
        path=None,
        exists=True,
        list_strategy="concatenate",
        data={
            "bead": {
                "task_types": [
                    {"use": "builtin@feature", "agent_creatable": False},
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [user_layer],
    )

    body, error = render_generated_task_types_memory_body(include_project_memory=False)
    assert error is None
    assert body is not None
    assert "### `feature`" not in body
    assert "### `bug`" in body
    assert "### `ci`" in body
    assert "### `flake`" in body
    assert "### `memory`" in body


def test_doctor_reports_plugins_required_and_task_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("plugins:\n  required:\n    - sase-github\n", encoding="utf-8")
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")

    monkeypatch.setattr(
        "sase.plugins.required._installed_plugin_versions",
        lambda *args, **kwargs: {"sase-github": "1.2.3"},
    )
    healthy_plugins = _check_plugins_required(context)
    assert healthy_plugins.status == "OK"

    monkeypatch.setattr(
        "sase.plugins.required._installed_plugin_versions",
        lambda *args, **kwargs: {},
    )
    broken_plugins = _check_plugins_required(context)
    assert broken_plugins.status == "ERROR"
    assert "required plugin `sase-github` is not installed" in broken_plugins.details[0]

    monkeypatch.setattr(
        "sase.task_types.get_task_type_registry",
        lambda: TaskTypeRegistry(records=(), diagnostics=()),
    )
    healthy_types = _check_task_types()
    assert healthy_types.status == "OK"

    monkeypatch.setattr(
        "sase.task_types.get_task_type_registry",
        lambda: TaskTypeRegistry(
            records=(),
            diagnostics=(
                TaskTypeDiagnostic(
                    code="duplicate_task_type",
                    message="plugin:extra duplicates builtin:sase",
                    severity="error",
                    task_type="bug",
                ),
            ),
        ),
    )
    broken_types = _check_task_types()
    assert broken_types.status == "ERROR"
    assert "duplicate_task_type" in broken_types.details[0]

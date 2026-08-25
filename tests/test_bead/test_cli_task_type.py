"""CLI coverage for ``sase bead task-type``."""

from __future__ import annotations

import io
import json
from types import MappingProxyType
from typing import Any

import pytest
from rich.console import Console

from sase.main.parser import create_parser, default_list_delegation_notice
from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)
from sase.task_types.cli_list import handle_task_type_list
from sase.task_types.cli_show import handle_task_type_show
from sase.task_types.registry import reset_task_type_registry_cache
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=160, color_system=None, highlight=False), buf


def _spec(**overrides: Any) -> dict[str, Any]:
    spec = {
        "schema_version": 1,
        "task_type": "flake",
        "label": "Flaky test",
        "summary": "A test that fails and then passes on an unchanged tree.",
        "when_to_use": "File one when a test failed and a rerun passed.",
        "glyph": "≈",
        "accent_color": "#00D7D7",
        "fields": [
            {
                "name": "node_id",
                "type": "string",
                "required": True,
                "role": ["data", "template"],
                "help": "The pytest node ID",
                "pattern": r"\S+::\S+",
            },
            {
                "name": "evidence",
                "type": "string",
                "required": True,
                "role": ["template"],
            },
        ],
        "body_template": "## Flake report\n\n{{ evidence }}\n",
        "triage": {"min_plus_ones": 1},
    }
    spec.update(overrides)
    return spec


def _record(
    spec: dict[str, Any],
    *,
    source: str = "builtin",
    package: str = "sase",
    builtin: bool = True,
    agent_creatable: bool | None = None,
) -> TaskTypeRecord:
    if agent_creatable is not None:
        spec = {**spec, "agent_creatable": agent_creatable}
    return TaskTypeRecord(
        task_type=str(spec["task_type"]),
        spec=MappingProxyType(spec),
        digest="a" * 64,
        provenance=TaskTypeProvenance(
            source=source,  # type: ignore[arg-type]
            name=package,
            package=package,
            version="1.0.0",
            builtin=builtin,
        ),
        resolved_glyph=str(spec.get("glyph") or "•"),
        resolved_accent_color=str(spec.get("accent_color") or "#5FAFFF"),
    )


def _registry(*records: TaskTypeRecord) -> TaskTypeRegistry:
    return TaskTypeRegistry(records=records, diagnostics=())


def test_task_type_group_defaults_to_list() -> None:
    parser = create_parser()
    omitted = parser.parse_args(["bead", "task-type"])
    explicit = parser.parse_args(["bead", "task-type", "list"])

    assert omitted.task_type_subcommand == "list"
    assert omitted.json is False
    assert omitted.all is False
    assert default_list_delegation_notice(omitted) == (
        "No subcommand provided for 'sase bead task-type'; "
        "delegating to 'sase bead task-type list'."
    )
    assert default_list_delegation_notice(explicit) is None


def test_task_type_help_lists_sorted_subcommands_and_default() -> None:
    group = parser_for(("sase", "bead", "task-type"))
    help_text = group.format_help()
    expected = {"list", "show"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{list,show}" in help_text
    assert "defaults to" in help_text.lower() or "delegates to" in help_text


def test_task_type_options_have_short_aliases() -> None:
    list_help = flat_help(
        parser_for(("sase", "bead", "task-type", "list")).format_help()
    )
    show_help = flat_help(
        parser_for(("sase", "bead", "task-type", "show")).format_help()
    )

    assert "-a, --all" in list_help
    assert "-j, --json" in list_help
    assert "-j, --json" in show_help
    assert "-r, --reason" not in show_help


def test_task_type_list_table_shows_slug_label_summary_source_and_agents() -> None:
    console, buf = _console()
    args = parse_sase_args(["bead", "task-type", "list"])
    registry = _registry(
        _record(_spec()),
        _record(
            _spec(
                task_type="github",
                label="GitHub",
                summary="A mirrored GitHub issue.",
                glyph="⑂",
                agent_creatable=False,
            ),
            source="plugin",
            package="sase-github",
            builtin=False,
            agent_creatable=False,
        ),
    )

    assert handle_task_type_list(args, console=console, registry=registry) == 0
    out = buf.getvalue()
    assert "flake" in out
    assert "Flaky test" in out
    assert "builtin" in out
    assert "yes" in out
    assert "github" not in out


def test_task_type_list_all_includes_uncreatable_types() -> None:
    console, buf = _console()
    args = parse_sase_args(["bead", "task-type", "list", "-a"])
    registry = _registry(
        _record(_spec()),
        _record(
            _spec(task_type="github", label="GitHub", agent_creatable=False),
            source="plugin",
            package="sase-github",
            builtin=False,
            agent_creatable=False,
        ),
    )

    assert handle_task_type_list(args, console=console, registry=registry) == 0
    out = buf.getvalue()
    assert "flake" in out
    assert "github" in out
    assert "no" in out


def test_task_type_list_json_payload(capsys: pytest.CaptureFixture[str]) -> None:
    args = parse_sase_args(["bead", "task-type", "list", "-j"])
    registry = _registry(_record(_spec()))

    assert handle_task_type_list(args, registry=registry) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["include_all"] is False
    assert payload["task_types"][0]["task_type"] == "flake"
    assert payload["task_types"][0]["source"] == "builtin"
    assert payload["task_types"][0]["agent_creatable"] is True


def test_task_type_show_prints_fields_template_triage_and_provenance() -> None:
    console, buf = _console()
    args = parse_sase_args(["bead", "task-type", "show", "flake"])

    assert (
        handle_task_type_show(
            args, console=console, registry=_registry(_record(_spec()))
        )
        == 0
    )
    out = buf.getvalue()
    assert "Flaky test" in out
    assert "flake" in out
    assert "File one when a test failed" in out
    assert "node_id" in out
    assert "required" in out
    assert "pattern:" in out
    assert "## Flake report" in out
    assert "min_plus_ones: 1" in out
    assert "builtin:sase" in out


def test_task_type_show_json_payload(capsys: pytest.CaptureFixture[str]) -> None:
    args = parse_sase_args(["bead", "task-type", "show", "flake", "-j"])

    assert handle_task_type_show(args, registry=_registry(_record(_spec()))) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["task_type"] == "flake"
    assert payload["triage"]["min_plus_ones"] == 1
    assert payload["fields"][0]["name"] == "node_id"
    assert payload["fields"][0]["pattern"] == r"\S+::\S+"
    assert payload["provenance"]["source"] == "builtin"


def test_task_type_show_json_payload_preserves_full_detail_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(["bead", "task-type", "show", "review", "-j"])
    record = _record(
        _spec(
            task_type="review",
            label="Review",
            summary="Review a completed patch.",
            when_to_use="File one when review evidence needs tracking.",
            create_refusal="Use the review workflow instead.",
            fields=[
                {
                    "name": "score",
                    "label": "Score",
                    "type": "integer",
                    "required": True,
                    "role": ["data"],
                    "help": "A bounded quality score",
                    "minimum": 1,
                    "maximum": 5,
                },
                {
                    "name": "category",
                    "label": "Category",
                    "type": "enum",
                    "required": False,
                    "role": ["template"],
                    "help": "Review category",
                    "values": ["bug", "design"],
                },
                {
                    "name": "evidence",
                    "label": "Evidence",
                    "type": "string",
                    "required": True,
                    "help": "A short evidence note",
                    "pattern": r"\S+",
                    "max_length": 200,
                },
            ],
            body_template="## Review\n\n{{ evidence }}\n",
            triage={"min_plus_ones": 2},
        ),
        source="plugin",
        package="sase-review",
        builtin=False,
        agent_creatable=False,
    )

    assert handle_task_type_show(args, registry=_registry(record)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "accent_color": "#00D7D7",
        "agent_creatable": False,
        "body_template": "## Review\n\n{{ evidence }}\n",
        "create_refusal": "Use the review workflow instead.",
        "digest": "a" * 64,
        "fields": [
            {
                "help": "A bounded quality score",
                "label": "Score",
                "maximum": 5,
                "minimum": 1,
                "name": "score",
                "required": True,
                "role": ["data"],
                "type": "integer",
            },
            {
                "help": "Review category",
                "label": "Category",
                "name": "category",
                "required": False,
                "role": ["template"],
                "type": "enum",
                "values": ["bug", "design"],
            },
            {
                "help": "A short evidence note",
                "label": "Evidence",
                "max_length": 200,
                "name": "evidence",
                "pattern": r"\S+",
                "required": True,
                "role": ["data", "template"],
                "type": "string",
            },
        ],
        "glyph": "≈",
        "label": "Review",
        "provenance": {
            "label": "plugin:sase-review",
            "package": "sase-review",
            "source": "plugin",
            "version": "1.0.0",
        },
        "schema_version": 1,
        "summary": "Review a completed patch.",
        "task_type": "review",
        "triage": {"min_plus_ones": 2},
        "when_to_use": "File one when review evidence needs tracking.",
    }


def test_task_type_show_prints_absence_for_missing_fields_and_template() -> None:
    console, buf = _console()
    args = parse_sase_args(["bead", "task-type", "show", "empty"])
    record = _record(
        _spec(
            task_type="empty",
            label="Empty",
            fields=[],
            body_template="",
            triage={},
        )
    )

    assert handle_task_type_show(args, console=console, registry=_registry(record)) == 0

    out = buf.getvalue()
    assert "[none]" not in out
    assert out.count("(none)") >= 2
    assert "CREATE REFUSAL" not in out


def test_task_type_list_includes_live_builtins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", lambda: []
    )
    monkeypatch.setenv("SASE_DISABLE_PLUGINS", "1")
    reset_task_type_registry_cache()
    console, buf = _console()
    args = parse_sase_args(["bead", "task-type", "list"])

    try:
        assert handle_task_type_list(args, console=console) == 0
    finally:
        reset_task_type_registry_cache()
    out = buf.getvalue()
    for slug in ("bug", "ci", "feature", "flake", "memory"):
        assert slug in out


def test_task_type_show_unknown_slug_lists_available(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(["bead", "task-type", "show", "nope"])

    assert handle_task_type_show(args, registry=_registry(_record(_spec()))) == 1
    err = capsys.readouterr().err
    assert "unknown task type: nope" in err
    assert "flake" in err

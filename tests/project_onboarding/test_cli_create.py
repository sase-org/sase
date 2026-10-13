"""Create-flow CLI contract tests split from ``test_cli``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.main import project_handler_add as add_cli
from sase.ops.models import DurableOperationRequest
from sase.workspace_provider._hookspec import ParsedRepoRef
from tests.main.parser_help_helpers import parser_for

from ._cli_test_support import long_option_order, make_create_args, make_plan


def test_parser_registers_sorted_create_options_and_rejects_bad_option() -> None:
    args = make_create_args(
        [
            "gh:team/demo",
            "--description",
            "Forge",
            "--visibility",
            "private",
            "--option",
            "template=org/tpl",
            "--yes",
        ]
    )
    assert args.project_subcommand == "create"
    assert args.description == "Forge"
    assert args.visibility == "private"
    assert args.option == ["template=org/tpl"]
    options = long_option_order(parser_for(("sase", "project", "create")).format_help())
    assert options == sorted(options)
    with pytest.raises(SystemExit, match="2"):
        make_create_args(["gh:team/demo", "--option", "not-a-pair"])
    with pytest.raises(SystemExit, match="2"):
        make_create_args(["gh:team/demo", "--setup", "--no-setup"])


def test_create_sugar_overlays_dash_o_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")
    monkeypatch.setattr(
        add_cli,
        "_target_for_ref",
        lambda _ref, **_kwargs: {
            "ref": "team/demo",
            "identity_key": "github.com/team/demo",
            "workflow_type": "gh",
        },
    )
    request = add_cli._request_from_args(
        make_create_args(
            [
                "gh:team/demo",
                "-O",
                "visibility=public",
                "-O",
                "description=from-O",
                "-v",
                "private",
                "-d",
                "from-d",
            ]
        ),
        mode="create",
        operation="project.create",
    )
    assert request["mode"] == "create"
    assert request["options"]["visibility"] == "private"
    assert request["options"]["description"] == "from-d"
    assert request["creation"]["visibility"] == "private"


def test_create_option_values_equal_to_transport_flags_are_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")
    monkeypatch.setattr(
        add_cli,
        "_target_for_ref",
        lambda _ref, **_kwargs: {
            "ref": "team/demo",
            "identity_key": "github.com/team/demo",
            "workflow_type": "gh",
        },
    )
    monkeypatch.setattr(
        add_cli,
        "parse_create_ref",
        lambda text: ParsedRepoRef(
            workflow_type="gh",
            ref="team/demo",
            identity_key="github.com/team/demo",
            display=text,
        ),
    )
    sidecar = {
        "mode": "create",
        "actor": "human",
        "target": {
            "ref": "team/demo",
            "workflow_type": "gh",
            "identity_key": "github.com/team/demo",
        },
        "requested": {
            "name": "",
            "aliases": [],
            "setup": "auto",
            "make_current": False,
        },
        "options": {
            "description": "--yes",
            "readme": "--json",
            "visibility": "private",
        },
        "creation": {"visibility": "private", "summary": []},
    }
    monkeypatch.setattr(add_cli, "resolve_request_path", lambda _args: Path("/request"))
    monkeypatch.setattr(
        add_cli,
        "load_request",
        lambda *_a, **_k: DurableOperationRequest(
            operation="project.create",
            payload={"request": sidecar},
        ),
    )
    request = add_cli._request_from_args(
        make_create_args(
            [
                "gh:team/demo",
                "--option",
                "description=--yes",
                "--option",
                "readme=--json",
                "--visibility",
                "private",
                "--yes",
                "--json",
            ]
        ),
        mode="create",
        operation="project.create",
    )
    assert request["options"] == sidecar["options"]


def test_create_apply_refuses_agent_with_gate_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    document = make_plan(
        blockers=[{"code": "human_only", "message": "create is human-only"}]
    )
    document["mode"] = "create"
    monkeypatch.setattr(
        add_cli, "_request_from_args", lambda _args, **_kwargs: {"mode": "create"}
    )
    monkeypatch.setattr(add_cli, "build_plan_document", lambda _request: document)
    monkeypatch.setattr(
        add_cli,
        "apply_plan",
        lambda *_a, **_k: pytest.fail("create apply must not run for agents"),
    )
    assert add_cli.handle_create(make_create_args(["gh:team/demo", "--yes"])) == 2
    err = capsys.readouterr().err
    assert "/sase_gate" in err
    assert "human approval" in err


def test_create_check_is_available_to_agents(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    document = make_plan(
        blockers=[{"code": "human_only", "message": "create is human-only"}]
    )
    document["mode"] = "create"
    document["creation_fields"] = [
        {
            "name": "visibility",
            "default": "private",
            "value": "private",
            "available": True,
        }
    ]
    monkeypatch.setattr(
        add_cli, "_request_from_args", lambda _args, **_kwargs: {"mode": "create"}
    )
    monkeypatch.setattr(add_cli, "build_plan_document", lambda _request: document)
    monkeypatch.setattr(
        add_cli,
        "apply_plan",
        lambda *_a, **_k: pytest.fail("check must not apply"),
    )
    assert add_cli.handle_create(make_create_args(["gh:team/demo", "--check"])) == 1
    out = capsys.readouterr().out
    assert "Plan: blocked" in out
    assert "visibility" in out


def test_create_gate_option_allows_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = make_plan()
    document["mode"] = "create"
    terminal = {
        "event": "result",
        "status": "ok",
        "project": {"key": "gh_team__demo", "name": "demo"},
        "next_argv": [],
        "message": "team/demo is ready",
    }
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_GATE_COMMAND", "1")
    monkeypatch.delenv("SASE_PROJECT_CREATE_BYPASS", raising=False)
    monkeypatch.setattr(
        add_cli,
        "_target_for_ref",
        lambda _ref, **_kwargs: {
            "ref": "team/demo",
            "identity_key": "github.com/team/demo",
            "workflow_type": "gh",
            "owner": "team",
        },
    )
    monkeypatch.setattr(add_cli, "resolve_request_path", lambda _args: None)
    seen: dict[str, Any] = {}

    def capture_plan(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return document

    monkeypatch.setattr(add_cli, "build_plan_document", capture_plan)
    monkeypatch.setattr(add_cli, "apply_plan", lambda *_a, **_k: terminal)
    assert add_cli.handle_create(make_create_args(["gh:team/demo", "--yes"])) == 0
    assert seen["actor"] == "human"


def test_create_bypass_prints_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.project_onboarding.human_only as human_only

    human_only._emitted_bypass_reasons.clear()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_PROJECT_CREATE_BYPASS", "repair-create")
    monkeypatch.delenv("SASE_GATE_COMMAND", raising=False)
    monkeypatch.setattr(
        add_cli,
        "_target_for_ref",
        lambda _ref, **_kwargs: {
            "ref": "team/demo",
            "identity_key": "github.com/team/demo",
            "workflow_type": "gh",
        },
    )
    request = add_cli._request_from_args(
        make_create_args(["gh:team/demo"]),
        mode="create",
        operation="project.create",
    )
    assert request["actor"] == "human"
    assert "repair-create" in capsys.readouterr().err

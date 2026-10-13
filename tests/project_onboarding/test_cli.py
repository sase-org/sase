"""CLI contract tests for project onboarding preview and apply."""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

import pytest

from sase import workspace_provider
from sase.main.parser import create_parser
from sase.main import project_handler_add as add_cli
from sase.ops.errors import OperationIOError
from sase.ops.models import DurableOperationRequest
from sase.project_onboarding.journal import lookup_journal
from sase.workspace_provider._hookspec import ParsedRepoRef, RepoProbe, WorkflowMetadata
from tests.main.parser_help_helpers import parser_for


def _parsed(tmp_path: Path, ref: str = "team/demo") -> ParsedRepoRef:
    owner, name = ref.split("/")
    return ParsedRepoRef(
        workflow_type="gh",
        ref=ref,
        identity_key=f"github.com/{owner}/{name}",
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=str(tmp_path / name),
        web_url=f"https://github.com/{ref}",
    )


def _plan(*, blockers: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "add",
        "status": "blocked" if blockers else "ready",
        "intent_fingerprint": "f" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "team/demo",
            "display": "team/demo",
            "identity_key": "github.com/team/demo",
            "visibility": "private",
            "default_branch": "main",
            "checkout_dir": "/tmp/demo",
            "can_push": True,
            "sase_managed": False,
        },
        "project": {
            "key": "gh_team__demo",
            "name": "demo",
            "aliases": [],
            "state": "enabled",
            "existing": False,
            "accent": "cyan",
        },
        "setup": {"enabled": True, "code": "unmanaged_can_push"},
        "steps": [
            {
                "id": "checkout",
                "label": "Clone and register",
                "operation": "create",
                "state": "pending",
            }
        ],
        "warnings": [],
        "blockers": blockers or [],
        "apply_argv": ["sase", "project", "add", "team/demo", "--yes", "--json"],
        "next_argv": [],
    }


def _args(parser_args: list[str]) -> Any:
    return create_parser(only="project").parse_args(["project", "add", *parser_args])


def _create_args(parser_args: list[str]) -> Any:
    return create_parser(only="project").parse_args(["project", "create", *parser_args])


def _long_option_order(help_text: str) -> list[str]:
    names: list[str] = []
    in_options = False
    for line in help_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("options:"):
            in_options = True
            continue
        if not in_options:
            continue
        # Option definition lines start with two spaces then a dash. Help
        # text may mention other flags (for example "sugar for --option").
        if not line.startswith("  -"):
            continue
        for match in re.finditer(r"--([a-z0-9-]+)", line):
            name = match.group(1)
            if name != "help" and name not in names:
                names.append(name)
    return names


def test_parser_registers_sorted_add_options_and_rejects_setup_conflict() -> None:
    args = _args(
        [
            "gh:team/demo",
            "--alias",
            "one",
            "-a",
            "two",
            "--name",
            "Demo",
            "--make-current",
            "--setup",
            "--yes",
            "--request-path",
            "/tmp/request.json",
        ]
    )
    assert args.project_subcommand == "add"
    assert args.alias == ["one", "two"]
    assert args.setup is True
    assert args.operation_request_path == "/tmp/request.json"
    options = _long_option_order(parser_for(("sase", "project", "add")).format_help())
    assert options == sorted(options)
    with pytest.raises(SystemExit, match="2"):
        _args(["gh:team/demo", "--setup", "--no-setup"])


def test_fake_provider_cli_check_emits_one_document_and_performs_no_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _parsed(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        workspace_provider,
        "get_all_workflow_metadata",
        lambda: [
            WorkflowMetadata(
                workflow_type="gh",
                ref_pattern="",
                display_name="GitHub",
                pre_allocated_env_prefix="",
                sdd_storage_policy="separate_repo",
            )
        ],
    )
    monkeypatch.setattr(workspace_provider, "get_display_name", lambda _kind: "GitHub")
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda kind, text: (
            repo if kind == "gh" and text.removeprefix("gh:") == repo.ref else None
        ),
    )
    monkeypatch.setattr(
        workspace_provider,
        "probe_repo",
        lambda _kind, _ref: RepoProbe(
            status="found",
            parsed=repo,
            visibility="private",
            default_branch="main",
            can_push=False,
            sase_managed=False,
            web_url=repo.web_url,
        ),
    )
    args = _args(["gh:team/demo", "--check", "--json"])
    assert add_cli.handle_add(args) == 0
    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert document["kind"] == "project_onboarding_plan"
    assert document["target"]["identity_key"] == repo.identity_key
    assert document["setup"]["enabled"] is False
    assert captured.err == ""
    assert not Path(repo.checkout_dir).exists()
    assert not (tmp_path / "sase-home" / "project_onboarding").exists()


def test_check_blocker_returns_one_without_calling_apply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _plan(blockers=[{"code": "checkout_conflict", "message": "occupied"}])
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args, **_kwargs: {})
    monkeypatch.setattr(add_cli, "build_plan_document", lambda _request: document)
    monkeypatch.setattr(
        add_cli, "apply_plan", lambda *_a, **_k: pytest.fail("check must not apply")
    )
    assert add_cli.handle_add(_args(["gh:team/demo", "--check"])) == 1
    assert "Plan: blocked" in capsys.readouterr().out


def test_explicit_agent_setup_refusal_uses_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _plan(blockers=[{"code": "human_only", "message": "human-only setup"}])
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args, **_kwargs: {})
    monkeypatch.setattr(add_cli, "build_plan_document", lambda _request: document)
    monkeypatch.setattr(
        add_cli,
        "apply_plan",
        lambda *_a, **_k: pytest.fail("blocked setup must not apply"),
    )
    args = _args(["gh:team/demo", "--setup", "--yes"])
    assert add_cli.handle_add(args) == 2
    assert "human-only setup" in capsys.readouterr().err


def test_json_apply_stream_and_result_file_share_terminal_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = _plan()
    request = {
        "mode": "add",
        "actor": "human",
        "target": {"ref": "team/demo", "identity_key": "github.com/team/demo"},
        "requested": {
            "setup": "auto",
            "aliases": [],
            "make_current": False,
            "name": "",
        },
    }
    terminal = {
        "event": "result",
        "status": "ok",
        "project": {"key": "gh_team__demo", "name": "demo"},
        "next_argv": [],
        "message": "team/demo is ready",
    }
    result_path = tmp_path / "result.json"
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args, **_kwargs: request)
    monkeypatch.setattr(add_cli, "build_plan_document", lambda _request: document)

    def fake_apply(_request: Any, *, emit: Any, plan: Any) -> dict[str, Any]:
        assert plan is document
        emit({"event": "plan", "plan": document})
        emit({"event": "step", "id": "checkout", "status": "done", "label": "Clone"})
        emit(terminal)
        return terminal

    monkeypatch.setattr(add_cli, "apply_plan", fake_apply)
    args = _args(["gh:team/demo", "--yes", "--json", "--result-path", str(result_path)])
    assert add_cli.handle_add(args) == 0
    output = capsys.readouterr()
    lines = [json.loads(line) for line in output.out.splitlines()]
    assert [line["event"] for line in lines] == ["plan", "step", "result"]
    stored = json.loads(result_path.read_text(encoding="utf-8"))
    assert stored["payload"] == lines[-1]
    assert output.err == ""


def test_tty_success_offers_init_and_records_its_terminal_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = _plan()
    request = {"mode": "add", "actor": "human", "target": {}, "requested": {}}
    result_path = tmp_path / "init-result.json"
    raw_result = {
        "event": "result",
        "status": "ok",
        "project": {"key": "gh_team__demo", "name": "demo"},
        "next_argv": ["sase", "init", "-p", "gh_team__demo"],
        "message": "team/demo is ready; run sase init",
    }
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args, **_kwargs: request)
    monkeypatch.setattr(add_cli, "build_plan_document", lambda _request: document)
    monkeypatch.setattr(add_cli, "_interactive_terminal", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    invoked: list[list[str]] = []

    def fake_run(argv: list[str], *, check: bool) -> Any:
        assert check is False
        invoked.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(add_cli.subprocess, "run", fake_run)

    def fake_apply(_request: Any, *, emit: Any, plan: Any) -> dict[str, Any]:
        emit({"event": "plan", "plan": document})
        emit(raw_result)
        return raw_result

    monkeypatch.setattr(add_cli, "apply_plan", fake_apply)
    args = _args(["gh:team/demo", "--yes", "--result-path", str(result_path)])
    assert add_cli.handle_add(args) == 0
    assert invoked == [["sase", "init", "-p", "gh_team__demo"]]
    stored = json.loads(result_path.read_text(encoding="utf-8"))
    assert stored["payload"]["status"] == "ok"
    assert stored["payload"]["next_argv"] == []
    assert "initialized" in stored["payload"]["message"]
    assert "initialized" not in capsys.readouterr().err


def test_non_tty_refuses_without_yes_and_does_not_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args, **_kwargs: {})
    monkeypatch.setattr(add_cli, "build_plan_document", lambda _request: _plan())
    monkeypatch.setattr(
        add_cli,
        "apply_plan",
        lambda *_a, **_k: pytest.fail("must refuse without --yes"),
    )
    monkeypatch.setattr(add_cli, "_interactive_terminal", lambda: False)
    output = io.StringIO()
    errors = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)
    monkeypatch.setattr("sys.stderr", errors)
    args = _args(["gh:team/demo"])
    assert add_cli.handle_add(args) == 1
    assert "Plan: ready" in output.getvalue()
    assert "re-run with --yes" in errors.getvalue()


def test_durable_request_must_match_argv_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = _parsed(Path("/tmp"))
    monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")
    monkeypatch.setattr(
        add_cli,
        "_target_for_ref",
        lambda _ref, **_kwargs: {
            "ref": parsed.ref,
            "identity_key": parsed.identity_key,
            "workflow_type": "gh",
        },
    )
    monkeypatch.setattr(add_cli, "resolve_request_path", lambda _args: Path("/request"))
    monkeypatch.setattr(
        add_cli,
        "parse_user_ref",
        lambda text, **_kwargs: ParsedRepoRef(
            workflow_type="gh",
            ref=text,
            identity_key="github.com/other/repo",
            display=text,
        ),
    )
    monkeypatch.setattr(
        add_cli,
        "load_request",
        lambda *_a, **_k: DurableOperationRequest(
            operation="project.add",
            payload={
                "mode": "add",
                "target": {"ref": "other/repo", "workflow_type": "gh"},
                "requested": {"setup": "auto"},
            },
        ),
    )
    with pytest.raises(OperationIOError, match="does not match"):
        add_cli._request_from_args(_args(["gh:team/demo"]))


def test_parser_registers_sorted_create_options_and_rejects_bad_option() -> None:
    args = _create_args(
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
    options = _long_option_order(
        parser_for(("sase", "project", "create")).format_help()
    )
    assert options == sorted(options)
    with pytest.raises(SystemExit, match="2"):
        _create_args(["gh:team/demo", "--option", "not-a-pair"])
    with pytest.raises(SystemExit, match="2"):
        _create_args(["gh:team/demo", "--setup", "--no-setup"])


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
        _create_args(
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
        _create_args(
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
    document = _plan(
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
    assert add_cli.handle_create(_create_args(["gh:team/demo", "--yes"])) == 2
    err = capsys.readouterr().err
    assert "/sase_gate" in err
    assert "human approval" in err


def test_create_check_is_available_to_agents(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _plan(
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
    assert add_cli.handle_create(_create_args(["gh:team/demo", "--check"])) == 1
    out = capsys.readouterr().out
    assert "Plan: blocked" in out
    assert "visibility" in out


def test_create_gate_option_allows_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _plan()
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
    assert add_cli.handle_create(_create_args(["gh:team/demo", "--yes"])) == 0
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
        _create_args(["gh:team/demo"]),
        mode="create",
        operation="project.create",
    )
    assert request["actor"] == "human"
    assert "repair-create" in capsys.readouterr().err


def _bare_git_create_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    from sase.project_onboarding import _apply_run as apply_mod
    from sase.workspace_provider.plugins import bare_git_workspace as bare_git

    home = tmp_path / "home"
    home.mkdir()
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setattr(
        bare_git.os.path,
        "expanduser",
        lambda value: (
            str(home / str(value)[2:]) if str(value).startswith("~/") else value
        ),
    )
    monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")
    monkeypatch.setattr(apply_mod, "detect_actor", lambda **_kwargs: "human")
    return home, sase_home


def test_bare_git_create_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, sase_home = _bare_git_create_home(tmp_path, monkeypatch)
    assert (
        add_cli.handle_create(
            _create_args(["git:tools", "--check", "--json", "--no-setup"])
        )
        == 0
    )
    document = json.loads(capsys.readouterr().out)
    argv = document["apply_argv"]
    assert argv[0:4] == ["sase", "project", "create", "git:tools"]
    assert "--visibility" not in argv
    assert "--no-setup" in argv
    emitted = create_parser(only="project").parse_args(argv[1:])
    assert add_cli.handle_create(emitted) == 0
    assert (sase_home / "repos" / "tools.git" / "HEAD").is_file()
    assert (home / "projects" / "git" / "tools" / ".git").exists()


def test_bare_git_create_honors_custom_bare_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sase_home = _bare_git_create_home(tmp_path, monkeypatch)
    custom_bare = tmp_path / "custom" / "tools.git"
    args = _create_args(
        [
            "git:tools",
            "--yes",
            "--no-setup",
            "--option",
            f"bare_dir={custom_bare}",
        ]
    )
    assert add_cli.handle_create(args) == 0
    assert (custom_bare / "HEAD").is_file()
    assert not (sase_home / "repos" / "tools.git").exists()
    assert (home / "projects" / "git" / "tools" / ".git").exists()


def test_bare_git_create_resumes_after_checkout_failure_with_custom_bare_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, sase_home = _bare_git_create_home(tmp_path, monkeypatch)
    from sase.workspace_provider.plugins.bare_git_workspace import (
        BareGitWorkspacePlugin,
    )

    custom_bare = tmp_path / "custom" / "tools.git"
    args = _create_args(
        [
            "git:tools",
            "--yes",
            "--no-setup",
            "--option",
            f"bare_dir={custom_bare}",
        ]
    )
    planned_identity = BareGitWorkspacePlugin().ws_parse_repo_ref("git", "tools")
    assert planned_identity is not None

    create_calls: list[tuple[Any, ...]] = []
    original_create = workspace_provider.create_repo

    def counted_create(*call_args: Any, **call_kwargs: Any) -> Any:
        create_calls.append(call_args)
        return original_create(*call_args, **call_kwargs)

    monkeypatch.setattr(workspace_provider, "create_repo", counted_create)
    original_resolve = workspace_provider.resolve_ref
    resolve_calls = 0
    resolved_refs: list[str] = []

    def fail_checkout_once(ref: str, workflow_type: str) -> Any:
        nonlocal resolve_calls
        resolve_calls += 1
        resolved_refs.append(ref)
        if resolve_calls == 1:
            raise RuntimeError("injected checkout failure")
        return original_resolve(ref, workflow_type)

    monkeypatch.setattr(workspace_provider, "resolve_ref", fail_checkout_once)
    assert add_cli.handle_create(args) == 1
    capsys.readouterr()
    first_journal = lookup_journal(planned_identity.identity_key)
    assert first_journal is not None
    assert first_journal["status"] == "failed"
    assert first_journal["remote"]["adopted_ref"] == str(custom_bare)
    assert first_journal["remote"]["adopted_identity_key"] == f"git:{custom_bare}"
    first_created_at = first_journal["remote"]["created_at"]
    assert (custom_bare / "HEAD").is_file()
    assert not (sase_home / "repos" / "tools.git").exists()

    assert add_cli.handle_create(args) == 0
    capsys.readouterr()
    resumed_journal = lookup_journal(planned_identity.identity_key)
    assert resumed_journal is not None
    assert resumed_journal["status"] == "complete"
    assert resumed_journal["remote"]["adopted_identity_key"] == f"git:{custom_bare}"
    assert len(create_calls) == 2  # The provider recognizes the existing bare path.
    assert resolve_calls == 2
    assert resolved_refs == [str(custom_bare), str(custom_bare)]
    assert resumed_journal["remote"]["created_at"] == first_created_at
    assert list(tmp_path.rglob("tools.git")) == [custom_bare]
    assert (home / "projects" / "git" / "tools" / ".git").exists()

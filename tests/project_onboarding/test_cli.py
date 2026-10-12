"""CLI contract tests for project onboarding preview and apply."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase import workspace_provider
from sase.main.parser import create_parser
from sase.main import project_handler_add as add_cli
from sase.ops.errors import OperationIOError
from sase.ops.models import DurableOperationRequest
from sase.workspace_provider._hookspec import ParsedRepoRef, RepoProbe, WorkflowMetadata


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
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args: {})
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
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args: {})
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
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args: request)
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
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args: request)
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
    monkeypatch.setattr(add_cli, "_request_from_args", lambda _args: {})
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
        lambda _ref: {
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

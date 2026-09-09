from __future__ import annotations

import argparse
import json
import sys
from types import SimpleNamespace

import pytest

from sase.dispatch.machine_service import _parse_enrollment_bundle
from sase.dispatch.models import BootstrapIssueResult
from sase.main.parser import create_parser, default_list_delegation_notice
from sase.main.machine_handler import _handle_bootstrap
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    flat_help,
    help_subcommand_rows,
    parser_for,
)


def test_machine_help_renders_sorted_subcommands_and_defaults_to_list() -> None:
    machine_parser = parser_for(("sase", "machine"))
    expected = {
        "add",
        "agent",
        "attention",
        "bootstrap",
        "discover",
        "init",
        "list",
        "remove",
        "rename",
        "repair",
        "status",
    }

    args = create_parser().parse_args(["machine"])

    assert args.machine_subcommand == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase machine'; delegating to 'sase machine list'."
    )
    assert help_subcommand_rows(machine_parser.format_help(), expected) == sorted(
        expected
    )
    assert (
        "{add,agent,attention,bootstrap,discover,init,list,remove,rename,repair,status}"
        in machine_parser.format_help()
    )


def test_machine_agent_help_documents_fork_retry_stop() -> None:
    agent_help = parser_for(("sase", "machine", "agent")).format_help()
    stop_help = flat_help(
        parser_for(("sase", "machine", "agent", "stop")).format_help()
    )
    fork_help = flat_help(
        parser_for(("sase", "machine", "agent", "fork")).format_help()
    )

    assert help_subcommand_rows(agent_help, {"fork", "retry", "stop"}) == [
        "fork",
        "retry",
        "stop",
    ]
    assert "ALIAS" in stop_help
    assert "AGENT" in stop_help
    assert "-j, --json" in stop_help
    assert_metavar_option_documented(stop_help, "-t", "--timeout", "SECONDS")
    assert "INSTRUCTION" in fork_help


def test_machine_add_help_has_no_secret_cli_value() -> None:
    add_help = flat_help(parser_for(("sase", "machine", "add")).format_help())

    assert "ALIAS" in add_help
    assert "ENDPOINT" in add_help
    assert_metavar_option_documented(add_help, "-B", "--bootstrap-file", "PATH")
    assert "no secret value is accepted as a command-line option" in add_help
    assert "sase machine init" in add_help
    assert "authenticated hello" in add_help
    assert "--bootstrap-secret" not in add_help


def test_machine_bootstrap_help_has_no_secret_cli_value() -> None:
    bootstrap_help = flat_help(
        parser_for(("sase", "machine", "bootstrap")).format_help()
    )

    assert_metavar_option_documented(bootstrap_help, "-e", "--expires", "SECONDS")
    assert "-j, --json" in bootstrap_help
    assert_metavar_option_documented(bootstrap_help, "-s", "--scope", "SCOPE")
    assert "same OS user and SASE home used by the gateway" in bootstrap_help
    assert "never accepted as a command-line argument" in bootstrap_help
    assert "--bootstrap-secret" not in bootstrap_help


def test_machine_bootstrap_parser_accepts_expiry_json_and_scopes() -> None:
    args = create_parser().parse_args(
        [
            "machine",
            "bootstrap",
            "--expires",
            "60",
            "--json",
            "--scope",
            "fleet.hello",
            "--scope",
            "fleet.summary.read",
        ]
    )

    assert args.machine_subcommand == "bootstrap"
    assert args.expires == 60
    assert args.json is True
    assert args.scope == ["fleet.hello", "fleet.summary.read"]


def test_machine_bootstrap_human_output_is_parseable_and_redacts_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "one-time-secret"
    pin = "sase_inst_v1_" + "a" * 64
    result = BootstrapIssueResult(
        bundle={
            "schema_version": 1,
            "bootstrap_id": "boot_1",
            "bootstrap_secret": secret,
            "expires_at_unix": 2_000_000_000.0,
            "pinned_installation_id": pin,
            "protocol_versions": [1],
            "requested_scopes": ["fleet.hello"],
        },
        bootstrap_id="boot_1",
        expires_at_unix=2_000_000_000.0,
        pinned_installation_id=pin,
        requested_scopes=("fleet.hello",),
    )
    service = SimpleNamespace(
        issue_bootstrap=lambda **_kwargs: result,
    )

    code = _handle_bootstrap(
        argparse.Namespace(json=False, expires=None, scope=None),
        service,  # type: ignore[arg-type]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert _parse_enrollment_bundle(captured.out).bootstrap_secret == secret
    assert secret not in captured.err
    assert "Secret: <redacted>" in captured.err


def test_machine_bootstrap_json_output_is_raw_bundle_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "one-time-secret"
    pin = "sase_inst_v1_" + "a" * 64
    result = BootstrapIssueResult(
        bundle={
            "schema_version": 1,
            "bootstrap_id": "boot_1",
            "bootstrap_secret": secret,
            "expires_at_unix": 2_000_000_000.0,
            "pinned_installation_id": pin,
            "protocol_versions": [1],
            "requested_scopes": [],
        },
        bootstrap_id="boot_1",
        expires_at_unix=2_000_000_000.0,
        pinned_installation_id=pin,
    )
    service = SimpleNamespace(
        issue_bootstrap=lambda **_kwargs: result,
    )

    code = _handle_bootstrap(
        argparse.Namespace(json=True, expires=30, scope=["fleet.hello"]),
        service,  # type: ignore[arg-type]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["bootstrap_secret"] == secret
    assert captured.out.count(secret) == 1
    assert captured.err == ""


def test_machine_init_help_documents_offline_check_and_hidden_bundle() -> None:
    init_help = flat_help(parser_for(("sase", "machine", "init")).format_help())
    alias_help = flat_help(parser_for(("sase", "init", "machine")).format_help())

    assert_metavar_option_documented(init_help, "-B", "--bootstrap-file", "PATH")
    assert "-c, --check" in init_help
    assert "-j, --json" in init_help
    assert_metavar_option_documented(init_help, "-t", "--timeout", "SECONDS")
    assert "no secret value is accepted as a command-line option" in init_help
    assert "--bootstrap-secret" not in init_help
    assert "performs no discovery" in init_help
    assert "sase machine init" in alias_help
    assert "Compatibility alias" in alias_help
    assert_metavar_option_documented(alias_help, "-B", "--bootstrap-file", "PATH")


def test_machine_init_parser_accepts_check_json_timeout_and_bundle_file() -> None:
    args = create_parser().parse_args(
        [
            "machine",
            "init",
            "--check",
            "--json",
            "--timeout",
            "2.5",
            "--bootstrap-file",
            "bundle.json",
        ]
    )

    assert args.machine_subcommand == "init"
    assert args.check is True
    assert args.json is True
    assert args.timeout == 2.5
    assert args.bootstrap_file == "bundle.json"


def test_init_machine_check_alias_does_not_discover(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry
    from sase.dispatch import providers

    def _fail_discovery(*args: object, **kwargs: object) -> object:
        raise AssertionError("init machine --check must not discover providers")

    monkeypatch.setattr(sys, "argv", ["sase", "init", "machine", "--check"])
    monkeypatch.setattr(providers, "discover_dispatch_candidates", _fail_discovery)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    assert "Checked: machine." in capsys.readouterr().out


def test_machine_init_check_does_not_discover(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry
    from sase.dispatch import providers

    def _fail_discovery(*args: object, **kwargs: object) -> object:
        raise AssertionError("machine init --check must not discover providers")

    monkeypatch.setattr(sys, "argv", ["sase", "machine", "init", "--check"])
    monkeypatch.setattr(providers, "discover_dispatch_candidates", _fail_discovery)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    assert "Checked: machine." in capsys.readouterr().out


def test_init_registry_runs_machine_after_config() -> None:
    from sase.main.init_registry import iter_init_command_specs

    names = [spec.name for spec in iter_init_command_specs()]

    assert names[:2] == ["config", "machine"]

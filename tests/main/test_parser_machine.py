from __future__ import annotations

import sys

import pytest

from sase.main.parser import create_parser, default_list_delegation_notice
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_machine_help_renders_sorted_subcommands_and_defaults_to_list() -> None:
    machine_parser = parser_for(("sase", "machine"))
    expected = {
        "add",
        "discover",
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
        "{add,discover,list,remove,rename,repair,status}"
        in machine_parser.format_help()
    )


def test_machine_add_help_has_no_secret_cli_value() -> None:
    add_help = flat_help(parser_for(("sase", "machine", "add")).format_help())

    assert "ALIAS" in add_help
    assert "ENDPOINT" in add_help
    assert "-B, --bootstrap-file" in add_help
    assert "no secret value is accepted as a command-line option" in add_help
    assert "--bootstrap-secret" not in add_help


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


def test_init_registry_runs_machine_after_config() -> None:
    from sase.main.init_registry import iter_init_command_specs

    names = [spec.name for spec in iter_init_command_specs()]

    assert names[:2] == ["config", "machine"]

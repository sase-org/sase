from __future__ import annotations

from types import SimpleNamespace

from sase.ops.commands.machine import handle_machine_agent_command


def test_machine_agent_refuses_unknown_subcommand() -> None:
    args = SimpleNamespace(
        machine_agent_subcommand="bogus",
        alias="apollo",
        agents=["worker"],
        timeout=None,
        json=False,
        operation_request_path=None,
        operation_result_path=None,
    )
    code = handle_machine_agent_command(args)
    assert code != 0

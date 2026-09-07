from __future__ import annotations

from types import SimpleNamespace

from sase.feature_flags import override_flags
from sase.ops.commands.machine import handle_machine_agent_command


def test_machine_agent_refuses_when_remote_dispatch_disabled() -> None:
    args = SimpleNamespace(
        machine_agent_subcommand="stop",
        alias="apollo",
        agents=["worker"],
        timeout=None,
        json=False,
        operation_request_path=None,
        operation_result_path=None,
    )
    with override_flags(remote_dispatch=False):
        code = handle_machine_agent_command(args)
    assert code != 0

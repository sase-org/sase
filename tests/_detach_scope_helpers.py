"""Shared fakes for the per-site ``detach_scope`` spawn tests."""

from __future__ import annotations

from sase.detach_scope import _DetachScopeCommand


def escaped_launch(argv: list[str]) -> _DetachScopeCommand:
    return _DetachScopeCommand(
        ["scope", *argv],
        start_new_session=False,
        escaped=True,
        method="systemd-run",
    )


def noop_launch(argv: list[str]) -> _DetachScopeCommand:
    return _DetachScopeCommand(list(argv), start_new_session=True)


def fake_popen_class(captured: dict[str, object], *, pid: int = 4321) -> type:
    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            captured["popen_argv"] = list(argv)
            captured["popen_kwargs"] = kwargs
            self.pid = pid

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int | None:
            return 0

    return FakePopen

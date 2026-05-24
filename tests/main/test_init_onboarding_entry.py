"""Entrypoint tests for bare ``sase init`` onboarding."""

from __future__ import annotations

import sys

import pytest

from tests.main.init_onboarding_helpers import (
    _changed_action,
    _plan,
    _spec,
)


def test_cli_main_dispatches_bare_init(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry, init_onboarding

    calls: list[str] = []
    specs = (_spec("memory", _plan("memory"), calls),)
    monkeypatch.setattr(init_onboarding, "iter_init_command_specs", lambda: specs)
    monkeypatch.setattr(sys, "argv", ["sase", "init"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    assert calls == []
    assert (
        "SASE is initialized. No init subcommands need to run."
        in capsys.readouterr().out
    )


def test_init_check_memory_alias_does_not_apply(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry, init_memory_handler

    def _fail_apply(*args: object, **kwargs: object) -> object:
        raise AssertionError("memory check mode must not apply generated files")

    monkeypatch.setattr(sys, "argv", ["sase", "init", "--check", "memory"])
    monkeypatch.setattr(
        init_memory_handler,
        "plan_init_memory",
        lambda args: _plan(
            "memory",
            actions=(_changed_action("memory/short/sase.md"),),
            summary="create memory files",
        ),
    )
    monkeypatch.setattr(init_memory_handler, "_initialize_memory_root", _fail_apply)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 1
    assert "create memory files" in capsys.readouterr().out


def test_init_check_sdd_alias_does_not_apply(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry, sdd_handler

    def _fail_apply(*args: object, **kwargs: object) -> object:
        raise AssertionError("SDD check mode must not apply generated files")

    monkeypatch.setattr(sys, "argv", ["sase", "init", "--check", "sdd"])
    monkeypatch.setattr(
        sdd_handler,
        "plan_sdd_init",
        lambda args: _plan(
            "sdd",
            actions=(_changed_action("sdd/README.md"),),
            summary="create SDD README files",
        ),
    )
    monkeypatch.setattr("sase.sdd.files.write_sdd_readme", _fail_apply)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 1
    assert "create SDD README files" in capsys.readouterr().out

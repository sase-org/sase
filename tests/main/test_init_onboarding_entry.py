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


def test_cli_main_rejects_all_with_explicit_alias(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "init", "--all", "memory"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 2
    assert "--all cannot be combined" in capsys.readouterr().err


def test_cli_main_dispatches_all_project_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import entry, init_onboarding

    seen: list[object] = []
    monkeypatch.setattr(
        init_onboarding,
        "run_init_onboarding_all",
        lambda args: seen.append(args) or 9,
    )
    monkeypatch.setattr(sys, "argv", ["sase", "init", "--all", "--check"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 9
    assert len(seen) == 1
    assert seen[0].all is True
    assert seen[0].check is True


def test_cli_main_rejects_project_with_explicit_alias(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "init", "-p", "alpha", "memory"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 2
    assert "--project cannot be combined" in capsys.readouterr().err


def test_cli_main_dispatches_named_project_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import entry, init_onboarding

    seen: list[object] = []
    monkeypatch.setattr(
        init_onboarding,
        "run_init_onboarding_all",
        lambda args: seen.append(args) or 4,
    )
    monkeypatch.setattr(
        sys, "argv", ["sase", "init", "-p", "alpha", "-p", "beta", "--check", "--json"]
    )

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 4
    assert len(seen) == 1
    assert seen[0].project == ["alpha", "beta"]
    assert seen[0].check is True
    assert seen[0].json is True
    assert seen[0].all is False


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
            actions=(_changed_action("memory/sase.md"),),
            summary="create memory files",
        ),
    )
    monkeypatch.setattr(init_memory_handler, "_initialize_memory_root", _fail_apply)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 1
    assert "create memory files" in capsys.readouterr().out


def test_init_check_config_alias_does_not_prompt_or_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import config_init_handler, entry

    monkeypatch.setattr(sys, "argv", ["sase", "init", "config", "--check"])
    monkeypatch.setattr(
        config_init_handler,
        "plan_config_init",
        lambda args: _plan(
            "config",
            actions=(_changed_action(".sase/machine_name"),),
            summary="choose a machine identity",
        ),
    )
    monkeypatch.setattr(
        config_init_handler,
        "_prompt_machine_name",
        lambda *_args, **_kwargs: pytest.fail("check mode must not prompt"),
    )

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 1
    assert "choose a machine identity" in capsys.readouterr().out


def test_init_check_skills_alias_does_not_apply(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry, init_skills_handler

    def _fail_apply(*args: object, **kwargs: object) -> object:
        raise AssertionError("skills check mode must not apply generated files")

    monkeypatch.setattr(sys, "argv", ["sase", "init", "--check", "skills"])
    monkeypatch.setattr(
        init_skills_handler,
        "plan_init_skills",
        lambda args: _plan(
            "skills",
            actions=(_changed_action(".claude/skills/foo/SKILL.md"),),
            summary="create skill files",
        ),
    )
    monkeypatch.setattr(init_skills_handler, "_load_skill_sources", _fail_apply)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 1
    assert "create skill files" in capsys.readouterr().out

"""Flow tests for bare ``sase init`` onboarding."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_plan import InitAction
from sase.main.init_registry import InitCommandSpec
from sase.main.sdd_handler import run_sdd_init
from sase.sdd.store import SddStore
from sase.workspace_provider import SddCompanionPreflight
from tests.main.init_onboarding_helpers import (
    _TtyStringIO,
    _args,
    _changed_action,
    _plan,
    _reject_prompt,
    _spec,
)


def test_noop_plans_print_initialized_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory"), calls),
        _spec("sdd", _plan("sdd"), calls),
        _spec("skills", _plan("skills"), calls),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "SASE is initialized. No init subcommands need to run." in out
    assert "Checked: memory, sdd, skills." in out


def test_bare_init_check_skips_sdd_outside_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory", summary="memory current"), calls),
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(_changed_action("sdd/README.md"),),
                summary="create SDD README files",
            ),
            calls,
        ),
        _spec("skills", _plan("skills", summary="skills current"), calls),
    )
    monkeypatch.setattr(init_onboarding, "iter_init_command_specs", lambda: specs)

    exit_code = run_init_onboarding(
        _args(check=True),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Checked: memory, skills." in out
    assert "init sdd" not in out
    assert calls == []


def test_bare_init_check_includes_sdd_inside_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory", summary="memory current"), calls),
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(_changed_action("sdd/README.md"),),
                summary="create SDD README files",
            ),
            calls,
        ),
        _spec("skills", _plan("skills", summary="skills current"), calls),
    )
    monkeypatch.setattr(init_onboarding, "iter_init_command_specs", lambda: specs)

    exit_code = run_init_onboarding(
        _args(check=True),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "init sdd" in out
    assert "create SDD README files" in out
    assert calls == []


def test_interactive_prompt_runs_only_confirmed_plan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    responses = iter(["yes", "n"])
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(_changed_action(),),
                summary="update 2 memory files",
            ),
            calls,
        ),
        _spec(
            "skills",
            _plan(
                "skills",
                actions=(_changed_action(".codex/skills/foo/SKILL.md"),),
                summary="write 5 provider skill files",
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=lambda prompt: next(responses),
    )

    assert exit_code == 0
    assert calls == ["memory"]
    out = capsys.readouterr().out
    assert "Needs attention:" in out
    assert "init memory" in out
    assert "init skills" in out


def test_interactive_prompt_eof_answers_no_without_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan("memory", actions=(_changed_action(),), summary="update memory"),
            calls,
        ),
    )

    def _raise_eof(prompt: str) -> str:
        raise EOFError

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_raise_eof,
    )

    assert exit_code == 0
    assert calls == []
    assert "Traceback" not in capsys.readouterr().err


def test_interactive_prompt_keyboard_interrupt_aborts_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan("memory", actions=(_changed_action(),), summary="update memory"),
            calls,
        ),
    )

    def _raise_interrupt(prompt: str) -> str:
        raise KeyboardInterrupt

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_raise_interrupt,
    )

    assert exit_code == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "confirmation cancelled; aborting" in out
    assert "Traceback" not in out


def test_full_drift_prompt_order_all_three_plans() -> None:
    calls: list[str] = []
    prompts: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan("memory", actions=(_changed_action(),), summary="update memory"),
            calls,
        ),
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(_changed_action("sdd/README.md"),),
                summary="update SDD files",
            ),
            calls,
        ),
        _spec(
            "skills",
            _plan(
                "skills",
                actions=(_changed_action(".codex/skills/foo/SKILL.md"),),
                summary="overwrite skills",
            ),
            calls,
        ),
    )

    def _answer(prompt: str) -> str:
        prompts.append(prompt)
        return "yes"

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_answer,
    )

    assert exit_code == 0
    assert calls == ["memory", "sdd", "skills"]
    assert [prompt.split(" now?", maxsplit=1)[0] for prompt in prompts] == [
        "Run `sase init memory`",
        "Run `sase init sdd`",
        "Run `sase init skills --force`",
    ]


def test_sdd_prompt_mentions_companion_repo_creation() -> None:
    calls: list[str] = []
    prompts: list[str] = []
    specs = (
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(
                    InitAction(
                        Path(".sase/sdd"),
                        "create",
                        "create or connect GitHub companion repository acme/widget--sdd",
                    ),
                ),
                summary="create companion repo",
            ),
            calls,
        ),
    )

    def _answer(prompt: str) -> str:
        prompts.append(prompt)
        return "yes"

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_answer,
    )

    assert exit_code == 0
    assert calls == ["sdd"]
    assert "This may create and push to a GitHub companion repository." in prompts[0]


@pytest.mark.parametrize(
    ("yes", "responses", "expected_prompt_count"),
    [
        (False, ["yes", "yes", "yes"], 3),
        (True, ["yes", "yes"], 2),
    ],
)
def test_bare_onboarding_requires_resource_confirmation_even_with_yes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    yes: bool,
    responses: list[str],
    expected_prompt_count: int,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    prompts: list[str] = []
    answers = iter(responses)
    authorizations: list[dict[str, bool] | None] = []
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.sdd._companion_init.preflight_split_sdd_companions",
        lambda _root, _workspace: {
            kind: SddCompanionPreflight(
                status="not_found",
                provider="GitHub",
                host="github.com",
                repo=f"acme/widget--{kind}",
                visibility="public",
            )
            for kind in ("plans", "research")
        },
    )

    def initialize(
        _root: Path,
        _workspace: int,
        *,
        creation_authorized: dict[str, bool] | None = None,
    ) -> SimpleNamespace:
        authorizations.append(creation_authorized)
        plans = tmp_path / "sase" / "repos" / "widget--plans"
        research = tmp_path / "sase" / "repos" / "widget--research"
        store = SddStore(
            "companion_repos",
            plans,
            plans,
            research_dir=research,
        )
        return SimpleNamespace(store=store)

    monkeypatch.setattr(
        "sase.sdd._companion_init.initialize_split_sdd_companions", initialize
    )
    plan = _plan(
        "sdd",
        actions=(
            InitAction(
                tmp_path / ".sase" / "sdd",
                "create",
                "create or connect GitHub companion repository acme/widget--sdd",
            ),
        ),
    )
    spec = InitCommandSpec("sdd", "SDD", lambda _args: plan, run_sdd_init)

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    exit_code = run_init_onboarding(
        _args(yes=yes),
        specs=(spec,),
        stdin=_TtyStringIO(),
        input_func=answer,
    )

    assert exit_code == 0
    assert len(prompts) == expected_prompt_count
    assert prompts[-1] == (
        "Create public GitHub SDD companion repository "
        "acme/widget--research on github.com? [y/N] "
    )
    assert authorizations == [{"plans": True, "research": True}]


def test_non_tty_drift_without_yes_prints_summary_and_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(_changed_action(),),
                summary="update 2 memory files",
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "Needs attention:" in out
    assert "update 2 memory files" in out
    assert "Run `sase init --yes` to apply these changes." in out


def test_check_mode_reports_drift_without_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(_changed_action("sdd/README.md"),),
                summary="update SDD README files",
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "Needs attention:" in out
    assert "update SDD README files" in out


def test_check_mode_does_not_apply_later_changed_plans() -> None:
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory", actions=(_changed_action(),)), calls),
        _spec(
            "skills",
            _plan("skills", actions=(_changed_action(".codex/skills/foo/SKILL.md"),)),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == []


def test_blocker_prints_and_exits_1_without_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(_changed_action(),),
                summary="update generated memory",
                blockers=("invalid sibling repo config",),
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(yes=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "Blockers:" in out
    assert "invalid sibling repo config" in out


def test_needs_attention_output_snapshot_lists_every_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec("sdd", _plan("sdd", summary="SDD current"), calls),
        _spec(
            "memory",
            _plan(
                "memory",
                summary="refresh 4 memory files",
                actions=(
                    InitAction(Path("memory/sase.md"), "update", "project memory"),
                    InitAction(Path("AGENTS.md"), "create", "project instructions"),
                    InitAction(Path("CLAUDE.md"), "overwrite", "provider shim"),
                    InitAction(Path("GEMINI.md"), "overwrite", "provider shim"),
                ),
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert capsys.readouterr().out == (
        "SASE initialization check\n"
        "\n"
        "Up to date:\n"
        "  ok   init sdd     SDD current\n"
        "\n"
        "Needs attention:\n"
        "  run  init memory  refresh 4 memory files\n"
        "       ~ update     memory/sase.md  –  project memory\n"
        "       + create     AGENTS.md       –  project instructions\n"
        "       ~ overwrite  CLAUDE.md       –  provider shim\n"
        "       ~ overwrite  GEMINI.md       –  provider shim\n"
    )


def test_interactive_prompt_diff_then_no_renders_diff_and_reprompts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text("old line\n", encoding="utf-8")
    calls: list[str] = []
    prompts: list[str] = []
    responses = iter(["d", "n"])
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(
                    InitAction(
                        target,
                        "update",
                        "managed agent instructions",
                        "new line\n",
                    ),
                ),
            ),
            calls,
        ),
    )

    def _answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    assert (
        run_init_onboarding(
            _args(),
            specs=specs,
            stdin=_TtyStringIO(),
            input_func=_answer,
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "@@ -1 +1 @@" in out
    assert "-old line" in out
    assert "+new line" in out
    assert len(prompts) == 2
    assert all(prompt.endswith("[y/N/d] ") for prompt in prompts)
    assert calls == []


def test_interactive_prompt_invalid_answer_prints_hint_and_reprompts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    responses = iter(["maybe", "n"])
    prompt_count = 0
    specs = (
        _spec(
            "memory",
            _plan("memory", actions=(_changed_action(),)),
            calls,
        ),
    )

    def _answer(_prompt: str) -> str:
        nonlocal prompt_count
        prompt_count += 1
        return next(responses)

    assert (
        run_init_onboarding(
            _args(),
            specs=specs,
            stdin=_TtyStringIO(),
            input_func=_answer,
        )
        == 0
    )

    assert "y = apply, n = skip, d = show diff" in capsys.readouterr().out
    assert prompt_count == 2
    assert calls == []


def test_check_diff_renders_full_diff_and_reports_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "README.md"
    target.write_text("before\n", encoding="utf-8")
    calls: list[str] = []
    specs = (
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(InitAction(target, "update", "README", "after\n"),),
            ),
            calls,
        ),
    )

    assert (
        run_init_onboarding(
            _args(check=True, diff=True),
            specs=specs,
            stdin=StringIO(),
            input_func=_reject_prompt,
        )
        == 1
    )

    out = capsys.readouterr().out
    assert "-before" in out
    assert "+after" in out
    assert calls == []


def test_warning_without_changes_is_visible_and_successful(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "skills",
            _plan(
                "skills",
                summary="provider skill files are current",
                warnings=("prettier not found",),
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Up to date:" in out
    assert "Warnings:" in out
    assert "init skills: prettier not found" in out

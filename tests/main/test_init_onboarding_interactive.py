"""Interactive confirmation tests for bare ``sase init`` onboarding."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_plan import InitAction
from sase.main.init_registry import InitCommandSpec
from sase.main.repo_init_handler import run_repo_init
from sase.sdd._sidecar_init import _SidecarInitOutcome, SidecarInitSpec
from sase.workspace_provider import SddSidecarPreflight
from tests.main.init_onboarding_helpers import (
    _TtyStringIO,
    _args,
    _changed_action,
    _plan,
    _spec,
)


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
            "repo",
            _plan(
                "repo",
                actions=(_changed_action("sase.yml"),),
                summary="update repository wiring",
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
    assert calls == ["memory", "repo", "skills"]
    assert [prompt.split(" now?", maxsplit=1)[0] for prompt in prompts] == [
        "Run `sase init memory`",
        "Run `sase init repo`",
        "Run `sase init skills --force`",
    ]


def test_repo_prompt_mentions_sidecar_repo_creation() -> None:
    calls: list[str] = []
    prompts: list[str] = []
    specs = (
        _spec(
            "repo",
            _plan(
                "repo",
                actions=(
                    InitAction(
                        Path("sase/repos/plans"),
                        "create",
                        "create or connect provider plans sidecar repository",
                    ),
                ),
                summary="create sidecar repo",
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
    assert calls == ["repo"]
    assert "This may create and push to a provider sidecar repository." in prompts[0]


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
    sidecars = (
        SidecarInitSpec(role="plans"),
        SidecarInitSpec(role="research"),
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: sidecars,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda _root, _workspace, _sidecars: {
            kind: SddSidecarPreflight(
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
        _sidecars: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
    ) -> _SidecarInitOutcome:
        authorizations.append(creation_authorized)
        plans = tmp_path / "sase" / "repos" / "plans"
        research = tmp_path / "sase" / "repos" / "research"
        return _SidecarInitOutcome(
            store=None,
            record=None,
            created=frozenset(),
            roots={"plans": plans, "research": research},
        )

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    plan = _plan(
        "repo",
        actions=(
            InitAction(
                tmp_path / "sase" / "repos" / "plans",
                "create",
                "create or connect provider plans sidecar repository",
            ),
        ),
    )
    spec = InitCommandSpec("repo", "Repos", lambda _args: plan, run_repo_init)

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
        "Create public GitHub sidecar repository "
        "acme/widget--research on github.com? [y/N] "
    )
    assert authorizations == [{"plans": True, "research": True}]


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

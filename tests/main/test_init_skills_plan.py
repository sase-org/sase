"""Tests for read-only ``sase init skills`` planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main import _init_skills_rendering as skills_rendering
from sase.main.init_skills_handler import (
    plan_init_skills,
    run_init_skills,
)
from tests.main.init_skills_handler_helpers import (
    make_args,
    stub_claude_skill_target,
    stub_skill_source,
)


def test_plan_missing_target_reports_create_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)

    plan = plan_init_skills(make_args(provider="claude"))

    assert [(action.operation, action.path) for action in plan.actions] == [
        ("create", target)
    ]
    assert isinstance(plan.actions[0].new_content, str)
    assert plan.actions[0].new_content.endswith("\nbody\n")
    assert "create 1 provider skill file" == plan.summary
    assert plan.warnings == (init_skills_handler._PRETTIER_WARNING,)
    assert not target.exists()
    assert not target.parent.exists()


@pytest.mark.parametrize(
    "render_result",
    [
        (None, "packaged SKILL.frame.template.md: template error: broken"),
        ("not frontmatter\n", None),
    ],
)
def test_broken_skill_frame_blocks_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    render_result: tuple[str | None, str | None],
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)
    monkeypatch.setattr(
        skills_rendering,
        "render_markdown_template",
        lambda **_kwargs: render_result,
    )

    plan = plan_init_skills(make_args(provider="claude"))

    assert plan.actions == ()
    assert any("SKILL.frame.template.md" in blocker for blocker in plan.blockers)
    assert run_init_skills(make_args(provider="claude")) == 1
    assert "SKILL.frame.template.md" in capsys.readouterr().err
    assert not target.exists()


def test_plan_identical_rendered_target_reports_no_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()

    plan = plan_init_skills(make_args(provider="claude"))

    assert target.exists()
    assert plan.actions == ()
    assert plan.summary == "provider skill files are current"


def test_plan_differing_target_reports_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)
    target.parent.mkdir(parents=True)
    target.write_text("stale skill\n", encoding="utf-8")

    plan = plan_init_skills(make_args(provider="claude"))

    assert [(action.operation, action.path) for action in plan.actions] == [
        ("overwrite", target)
    ]
    assert plan.actions[0].new_content != "stale skill\n"
    assert plan.summary == "overwrite 1 provider skill file"


def test_check_defers_dirty_chezmoi_source_drift_as_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drift the deploy-side guard would refuse is a warning, not a failure."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(
        init_skills_handler, "CHEZMOI_HOME", tmp_path / "chezmoi" / "home"
    )
    integrity_error = (
        "refusing chezmoi skill deploy because xprompt sources have "
        "uncommitted changes:\n  M src/sase/xprompts/skills/foo.md"
    )
    monkeypatch.setattr(
        init_skills_handler, "skill_source_integrity_error", lambda: integrity_error
    )

    plan = plan_init_skills(make_args(check=True, provider="claude"))

    assert plan.actions == ()
    assert plan.blockers == ()
    assert plan.summary == "provider skill files are current"
    assert (
        "1 provider skill file out of sync with rendered sources; redeploy is "
        "deferred until land. Rerun `sase init skills` after landing."
    ) in plan.warnings
    assert integrity_error in plan.warnings
    assert run_init_skills(make_args(check=True, provider="claude")) == 0


def test_check_defers_clean_but_stale_chezmoi_drift_as_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean, already-landed but undeployed source is deferred too."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(
        init_skills_handler, "CHEZMOI_HOME", tmp_path / "chezmoi" / "home"
    )
    monkeypatch.setattr(
        init_skills_handler, "skill_source_integrity_error", lambda: None
    )

    plan = plan_init_skills(make_args(check=True, provider="claude"))

    assert plan.actions == ()
    assert (
        "1 provider skill file out of sync with rendered sources; redeploy is "
        "deferred until land. Rerun `sase init skills` after landing."
    ) in plan.warnings
    assert run_init_skills(make_args(check=True, provider="claude")) == 0


def test_non_check_plan_still_reports_actionable_chezmoi_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside ``--check``, onboarding still sees real drift to offer applying."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(
        init_skills_handler, "CHEZMOI_HOME", tmp_path / "chezmoi" / "home"
    )
    monkeypatch.setattr(
        init_skills_handler,
        "skill_source_integrity_error",
        lambda: "refusing chezmoi skill deploy because HEAD is not an ancestor",
    )

    plan = plan_init_skills(make_args(provider="claude"))

    assert [action.operation for action in plan.actions] == ["create"]
    assert plan.warnings == ()


def test_plan_honors_provider_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_claude_skill_target(tmp_path, monkeypatch)

    plan = plan_init_skills(make_args(provider="codex"))

    assert plan.actions == ()
    assert plan.warnings == ()


def test_plan_unknown_provider_reports_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_claude_skill_target(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "_all_providers", lambda: ["claude"])

    plan = plan_init_skills(make_args(provider="not-a-provider"))

    assert plan.actions == ()
    assert plan.blockers == (
        "unknown provider 'not-a-provider'; registered providers: claude",
    )

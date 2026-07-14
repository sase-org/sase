"""Tests for shipped ``sase init skills`` source discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import (
    _get_target_path,
    _get_target_paths,
    get_skill_target_providers,
    handle_init_skills_command,
)
from sase.xprompt.loader import get_sase_package_xprompts_dir
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import make_args


@pytest.mark.parametrize(
    ("skill_name", "expected_phrases"),
    [
        ("sase_artifact", ("sase artifact create -p", "--kind")),
        (
            "sase_agents_status",
            (
                "sase agent list -j",
                "artifacts_dir",
                "cite the artifact paths",
            ),
        ),
        (
            "sase_chats",
            (
                "sase chat list -j",
                "sase chat show",
                "/sase_agents_status",
                "draft/live",
            ),
        ),
        (
            "sase_beads",
            (
                "SASE_SDD_PLANS_DIR=$(sase sdd path plans)",
                "SASE_SDD_BEADS_DIR=$(sase sdd path beads)",
                "${SASE_SDD_PLANS_DIR}/202605/auth.md",
            ),
        ),
        (
            "sase_memory_read",
            (
                "sase memory read",
                "--reason",
                "## Children",
            ),
        ),
        ("sase_notify", ("sase notify list -j", "sase notify show --id")),
        ("sase_plan", ("sase plan propose sase_plan_<name>.md",)),
        (
            "sase_project",
            (
                "sase project list --json",
                "effective_project_name",
                "sase project disable <project>",
                "sase project alias list",
                "/sase_run",
                "/sase_repo",
            ),
        ),
        (
            "sase_repo",
            (
                "sase repo open sase-github",
                "sase repo open dotdrop",
                "sase repo open gh:pallets/click",
                "Use that printed path as the only path",
                "sase repo list",
                "sase repo log",
            ),
        ),
        (
            "sase_run",
            (
                "sase launch request",
                "launch_response.json",
                "%n(parent, reviewer)",
                "Do not run `sase run`",
                "#git:home",
                "%w(",
                "sase xprompt list",
                "%xprompts_enabled:false",
                "sase xprompt expand",
                "max_slots_exceeded",
            ),
        ),
        (
            "sase_var",
            (
                "sase var set KEY=VALUE",
                "%name:build-@",
                '{{ agents["build"].result_path }}',
                "Telegram completion message",
                "sase var set STOP=1",
                "only affects later `%repeat` / `%r` slots",
            ),
        ),
    ],
)
def test_shipped_skill_source_is_discoverable_for_all_skill_providers(
    skill_name: str,
    expected_phrases: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shipped ``skill: true`` sources render to every deployable provider."""
    src = get_sase_package_xprompts_dir() / "skills" / f"{skill_name}.md"
    assert src.is_file(), f"missing skill source: {src}"

    front_matter, body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))
    assert front_matter is not None
    assert front_matter.get("name") == skill_name
    assert front_matter.get("skill") is True
    assert front_matter.get("description")
    assert body.strip(), "skill body must not be empty"
    for phrase in expected_phrases:
        assert phrase in body

    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())
    assert exc.value.code == 0

    providers = get_skill_target_providers(True)
    assert providers, "expected at least one registered llm provider"

    for provider in providers:
        target = _get_target_path(provider, skill_name, use_chezmoi=False)
        assert target.exists(), f"{skill_name} not generated for provider {provider}"
        rendered = target.read_text(encoding="utf-8")
        for phrase in expected_phrases:
            assert phrase in rendered


@pytest.mark.parametrize("skill_name", ["sase_git_commit", "sase_hg_commit"])
def test_commit_skill_sources_do_not_reference_legacy_bead_flag(
    skill_name: str,
) -> None:
    """Commit skills should rely on SASE_BEAD_ID rather than a commit flag."""
    src = get_sase_package_xprompts_dir() / "skills" / f"{skill_name}.md"
    body = src.read_text(encoding="utf-8")
    assert "--bead-id" not in body
    assert "sase bead list --status=in_progress" not in body


def test_git_commit_skill_invokes_observable_wrapper() -> None:
    """The git commit skill should call the wrapper, not raw ``sase commit``."""
    src = get_sase_package_xprompts_dir() / "skills" / "sase_git_commit.md"
    body = src.read_text(encoding="utf-8")
    assert "Commit changes via the `sase_git_commit` wrapper" in body
    assert "records skill invocation evidence" in body
    assert "sase_git_commit -M commit_message.md" in body
    assert "use one `-f` flag for each listed file" in body
    assert "reserve that for an intentional" in body
    assert "deleted only after a successful commit" in body
    assert "Do not preemptively stash, fast-forward, pull, or hand-sync" in body
    assert "`2`: A rebase is paused for a real conflict" in body
    assert "sase_git_commit --resume" in body
    assert "sase commit -M commit_message.md" not in body
    assert "sase commit --resume" not in body


def test_agy_skill_generation_writes_antigravity_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-scoped skill is written to that provider's deployment profile."""
    xprompt = XPrompt(
        name="agy_only",
        content="Antigravity profile body.\n",
        description="Antigravity profile test skill.",
        skill=["agy"],
    )
    monkeypatch.setattr(init_skills_handler, "load_xprompts_from_internal", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"agy_only": xprompt},
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    for target in _get_target_paths("agy", "agy_only", use_chezmoi=False):
        assert target.exists(), f"missing generated skill target: {target}"
        assert "Antigravity profile body." in target.read_text(encoding="utf-8")


def test_config_defined_skill_is_generated_from_loaded_xprompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Config-overlay xprompts with ``skill`` participate in init skills."""
    xprompt = XPrompt(
        name="sase_gmail",
        content="Use gog for Gmail.\n",
        source_path="config_overlay:sase_athena.yml",
        description="Read-only personal Gmail access through gog.",
        skill=True,
    )
    monkeypatch.setattr(init_skills_handler, "load_xprompts_from_internal", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"sase_gmail": xprompt},
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True, provider="codex"))

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(_get_target_path("codex", "sase_gmail", use_chezmoi=False)) in out
    assert "Dry run: 1 source entries, no files written" in out


def test_skill_provider_list_respects_requested_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``skill: [codex]`` only renders for codex, including with --provider."""
    xprompt = XPrompt(
        name="codex_only",
        content="Only for Codex.\n",
        description="Codex-only skill.",
        skill=["codex"],
    )
    monkeypatch.setattr(init_skills_handler, "load_xprompts_from_internal", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"codex_only": xprompt},
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True))

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(_get_target_path("codex", "codex_only", use_chezmoi=False)) in out
    assert "claude/skills/codex_only" not in out

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True, provider="claude"))

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(_get_target_path("codex", "codex_only", use_chezmoi=False)) not in out
    assert "Dry run: 1 source entries, no files written" in out

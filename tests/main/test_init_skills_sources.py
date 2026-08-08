"""Tests for shipped ``sase init skills`` source discovery."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.main import init_skills_handler
from sase.main import _init_skills_source_integrity as source_integrity
from sase.main.init_skills_handler import (
    _get_target_path,
    _get_target_paths,
    get_skill_target_providers,
    handle_init_skills_command,
)
from sase.xprompt.loader import get_sase_package_skills_dir
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import make_args


def _collapse_whitespace(text: str) -> str:
    """Return ``text`` with every whitespace run flattened to one space.

    Skill prose is wrapped at the repo Markdown width, so phrase assertions
    must not depend on where the line breaks happen to land.
    """
    return " ".join(text.split())


def test_skill_source_integrity_allows_clean_merged_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    skills_dir = repo_root / "src" / "sase" / "skills"
    skills_dir.mkdir(parents=True)
    calls: list[tuple[str, ...]] = []

    def fake_run_git(root: Path, *args: str) -> str:
        calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo_root)
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(
        source_integrity, "get_sase_package_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(
        source_integrity, "get_default_branch", lambda _root: "origin/main"
    )
    monkeypatch.setattr(source_integrity, "run_git", fake_run_git)

    assert source_integrity.skill_source_integrity_error() is None
    assert (
        "status",
        "--porcelain=v1",
        "--",
        "src/sase/skills",
    ) in calls
    assert (
        "merge-base",
        "--is-ancestor",
        "HEAD",
        "origin/main",
    ) in calls


def test_skill_source_integrity_reports_dirty_skill_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    skills_dir = repo_root / "src" / "sase" / "skills"
    skills_dir.mkdir(parents=True)

    def fake_run_git(root: Path, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo_root)
        if args[:2] == ("status", "--porcelain=v1"):
            return " M src/sase/skills/foo.md"
        raise AssertionError(args)

    monkeypatch.setattr(
        source_integrity, "get_sase_package_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(source_integrity, "run_git", fake_run_git)

    error = source_integrity.skill_source_integrity_error()

    assert error is not None
    assert "uncommitted changes" in error
    assert "src/sase/skills/foo.md" in error
    assert "Land the skill source change" in error
    assert "--allow-dirty" in error


def test_skill_source_integrity_reports_commits_missing_from_canonical_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    skills_dir = repo_root / "src" / "sase" / "skills"
    skills_dir.mkdir(parents=True)

    def fake_run_git(root: Path, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo_root)
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            raise subprocess.CalledProcessError(1, ["git", *args])
        if args[:2] == ("log", "--format=%h %s"):
            return "abc1234 feat: unlanded skill source"
        raise AssertionError(args)

    monkeypatch.setattr(
        source_integrity, "get_sase_package_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(
        source_integrity, "get_default_branch", lambda _root: "origin/master"
    )
    monkeypatch.setattr(source_integrity, "run_git", fake_run_git)

    error = source_integrity.skill_source_integrity_error()

    assert error is not None
    assert "HEAD is not an ancestor of origin/master" in error
    assert "abc1234 feat: unlanded skill source" in error


@pytest.mark.parametrize(
    ("skill_name", "expected_phrases"),
    [
        (
            "sase_artifact_file",
            (
                "sase artifact create -p",
                "--kind",
                "--move",
                "sase artifact list",
                "sase artifact show",
                "sase artifact path",
                "sase artifact open",
                "sase artifact doctor",
                'sase artifact create -p <path> -l "<label>" --bead',
            ),
        ),
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
            "sase_gate",
            (
                "beautiful, robust, and powerful custom notification gates",
                "dangerous or irreversible command",
                '"query": "(restart AND verify) OR reject"',
                '"default_selected": true',
                '"feedback": "required"',
                '"groups": [',
                '"panel": "deployments"',
                '"panel_icon": "🚀"',
                "`presentation.origin_agent`",
                "sase gate create",
                "sase gate wait",
                "selected_option_ids",
                "Never poll bundle files directly",
                "Never run bundle commands by hand",
                "Automatic resolution is forbidden for custom gates",
            ),
        ),
        (
            "sase_changespecs",
            (
                "sase changespec current -f markdown",
                "sase changespec search '<query>' -f markdown",
                "ChangeSpecs can carry a `REFS:` section",
                "sase changespec ref add -c <name>",
                "project.changespec_refs",
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
        (
            "sase_new_task",
            (
                "sase memory read sase_beads.md",
                "sase bead list --type task --format full --limit 0",
                "sase bead +1 <task-id>",
                "Do not create a task",
                "same underlying defect/root cause or desired remediation",
                "sase bead list --type plan --tier epic --status in_progress",
                "DISCOVERED ISSUE:",
                "If both the duplicate and active-epic branches apply, record both",
                "sase bead create -T task",
                "--size <size>",
                "xsmall",
                "xlarge",
            ),
        ),
        (
            "sase_notify",
            (
                "sase notify list -j",
                "sase notify show --id",
                "interaction_requests/<kind>/<request-id>/request.json",
                "sase gate create",
                "sase gate wait",
                "CustomGate",
                "/sase_gate",
                '"silent": true',
            ),
        ),
        (
            "sase_plan",
            (
                "Use `tale`",
                "Use `epic`",
                "unique slug ID",
                "`tier: <tier>`",
                "`<tier>` is either `tale` or `epic`",
                "sase plan validate sase_plan_<name>.md --explain",
                "sase plan validate sase_plan_<name>.md",
                "expected schema and all diagnostics",
                "Do not propose a plan that has not passed validation",
                "sase plan propose sase_plan_<name>.md",
                "writes a handoff marker",
                "do not poll response files yourself",
            ),
        ),
        (
            "sase_questions",
            (
                "sase questions '<json>'",
                "writes a durable handoff marker",
                "sends `SIGTERM`",
                "Do not poll question request or response files",
            ),
        ),
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
                "sase repo open gh:steveyegge/beads",
                "Use that printed path as the only path",
                "Do not web-fetch",
                "raw.githubusercontent.com",
                "GitHub issue and PR discussions",
                "sase repo list",
                "sase repo log",
            ),
        ),
        (
            "sase_run",
            (
                "sase launch request",
                '"status": "approved"',
                '"selected_option_ids": ["approve"]',
                "do not poll request files yourself",
                "%i(reviewer, family=parent)",
                "Do not run `sase run`",
                "#git:home",
                "%w(",
                "sase xprompt list",
                "%xprompts_enabled:false",
                "sase xprompt expand",
                "max_slots_exceeded",
                "interaction_requests/launch/<request-id>/",
            ),
        ),
        (
            "sase_var",
            (
                "sase var set KEY=VALUE",
                "sase var list --json",
                "1,024 total nodes",
                "Map keys are stored and displayed in sorted order",
                "%id:build-@",
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
    src = get_sase_package_skills_dir() / f"{skill_name}.md"
    assert src.is_file(), f"missing skill source: {src}"

    front_matter, body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))
    assert front_matter is not None
    assert front_matter.get("name") == skill_name
    assert front_matter.get("skill") is True
    assert front_matter.get("description")
    assert body.strip(), "skill body must not be empty"
    # Compare on collapsed whitespace: prose phrases straddle line breaks that
    # move whenever the Markdown prose width changes.
    flat_body = _collapse_whitespace(body)
    for phrase in expected_phrases:
        assert _collapse_whitespace(phrase) in flat_body

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
        rendered = _collapse_whitespace(target.read_text(encoding="utf-8"))
        for phrase in expected_phrases:
            assert _collapse_whitespace(phrase) in rendered


def test_gate_skill_sources_do_not_reference_v1_contract() -> None:
    """Generated gate guidance must use the query-driven v2 interface."""
    skills_dir = get_sase_package_skills_dir()

    for skill_name in ("sase_gate", "sase_notify", "sase_run"):
        body = (skills_dir / f"{skill_name}.md").read_text(encoding="utf-8")
        for stale_phrase in (
            "sase notify create --gate",
            "sase notify wait",
            "choice_id",
            "selected_extra_ids",
        ):
            assert stale_phrase not in body


def test_sase_plan_skill_does_not_expose_internal_model_aliases() -> None:
    """Planning guidance describes behavior without exposing routing internals."""
    src = get_sase_package_skills_dir() / "sase_plan.md"
    body = src.read_text(encoding="utf-8")

    for internal_name in (
        "phase_worker",
        "cheap",
        "cheaper",
        "cheapest",
        "smart",
        "smartest",
        "xsmall_phase_worker",
        "small_phase_worker",
        "medium_phase_worker",
        "large_phase_worker",
        "xlarge_phase_worker",
    ):
        assert internal_name not in body


def test_sase_repo_skill_description_covers_web_fetches() -> None:
    """The always-visible skill trigger closes the repository web-fetch loophole."""
    src = get_sase_package_skills_dir() / "sase_repo.md"
    front_matter, _body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))

    assert front_matter is not None
    description = str(front_matter.get("description", ""))
    assert "web-fetching a repo's files or history" in description
    assert "raw.githubusercontent.com" in description
    assert "GitHub API" in description


@pytest.mark.parametrize("skill_name", ["sase_git_commit", "sase_hg_commit"])
def test_commit_skill_sources_do_not_reference_legacy_bead_flag(
    skill_name: str,
) -> None:
    """Commit skills should rely on SASE_BEAD_ID rather than a commit flag."""
    src = get_sase_package_skills_dir() / f"{skill_name}.md"
    body = src.read_text(encoding="utf-8")
    assert "--bead-id" not in body
    assert "sase bead list --status=in_progress" not in body


def test_git_commit_skill_invokes_observable_wrapper() -> None:
    """The git commit skill should call the wrapper, not raw ``sase commit``."""
    src = get_sase_package_skills_dir() / "sase_git_commit.md"
    body = src.read_text(encoding="utf-8")
    flat = _collapse_whitespace(body)
    assert "Commit changes via the `sase_git_commit` wrapper" in flat
    assert "records skill invocation evidence" in flat
    assert "sase_git_commit -M .sase/commit_message.md" in body
    assert "use one `-f` flag for each listed file" in body
    assert "reserve that for an intentional" in body
    assert "deleted only after a successful commit" in body
    assert "Do not preemptively stash, fast-forward, pull, or hand-sync" in body
    assert "`2`: A rebase is paused for a real conflict" in body
    assert "sase_git_commit --resume" in body
    assert "git-ignored" in body
    assert "sase commit -M" not in body
    assert "-M commit_message.md" not in body
    assert "sase commit --resume" not in body


def test_agy_skill_generation_writes_antigravity_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-scoped skill is written to that provider's deployment profile."""
    xprompt = XPrompt(
        name="skills/agy_only",
        content="Antigravity profile body.\n",
        description="Antigravity profile test skill.",
        skill=["agy"],
        skill_name="agy_only",
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"skills/agy_only": xprompt},
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


def test_config_defined_skill_is_rejected_with_a_migration_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A config entry can never be a skill: it has no file to generate from."""
    from sase.xprompt.loader_parsing import parse_xprompt_entries

    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": parse_xprompt_entries(
            {
                "sase_gmail": {
                    "content": "Use gog for Gmail.\n",
                    "description": "Read-only personal Gmail access through gog.",
                    "skill": True,
                }
            },
            "config_overlay:sase_athena.yml",
        ),
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True, provider="codex"))

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert str(_get_target_path("codex", "sase_gmail", use_chezmoi=False)) not in (
        captured.out
    )
    assert "declares `skill:` outside a canonical skill source" in captured.err
    assert "sase/skills/" in captured.err


def test_skill_provider_list_respects_requested_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``skill: [codex]`` only renders for codex, including with --provider."""
    xprompt = XPrompt(
        name="skills/codex_only",
        content="Only for Codex.\n",
        description="Codex-only skill.",
        skill=["codex"],
        skill_name="codex_only",
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"skills/codex_only": xprompt},
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

"""Tests for SDD file writing and frontmatter utilities."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.directory_map_assets import DIRECTORY_MAP_ASSET_OVERRIDE_ENV
from sase.sdd.committed_plan_validation import _CommittedPlanValidationError
from sase.sdd.files import (
    ensure_bare_git_sdd_initialized,
    ensure_sdd_initialized,
    expected_sdd_generated_paths,
    expected_sdd_readme,
    set_prompt_qa,
    update_prompt_with_qa,
    update_spec_with_qa,
    write_sdd_readme,
    write_sdd_files,
    write_sdd_spec,
)
from sase.sdd._commit import commit_bare_git_sdd_init_paths
from sase.sdd._paths import get_yyyymm
from sase.sdd.artifact_links import parse_sdd_artifact_link
from sase.logs import tui_git_ops_jsonl_path
from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields

_GIT_AVAILABLE = shutil.which("git") is not None


def _git(repo: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# write_sdd_files
# ---------------------------------------------------------------------------


def test_ensure_sdd_initialized_writes_generated_files(
    tmp_path: Path,
    real_directory_map_assets: None,
) -> None:
    refreshed = ensure_sdd_initialized(tmp_path)

    expected = set(expected_sdd_generated_paths(str(tmp_path)))
    assert set(refreshed) == expected
    assert all(path.exists() for path in expected)
    directory_map = tmp_path / "sdd" / "assets" / "sdd-directory-map.png"
    assert directory_map.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_ensure_sdd_initialized_uses_directory_map_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override = tmp_path / "placeholder.bin"
    override.write_bytes(b"small directory map")
    monkeypatch.setenv(DIRECTORY_MAP_ASSET_OVERRIDE_ENV, str(override))
    root = tmp_path / "repo"

    ensure_sdd_initialized(root)

    directory_map = root / "sdd" / "assets" / "sdd-directory-map.png"
    assert directory_map.read_bytes() == b"small directory map"


def test_ensure_sdd_initialized_skips_current_tree(tmp_path: Path) -> None:
    write_sdd_readme(str(tmp_path))

    with patch("sase.sdd.files.write_sdd_readme") as write_readme:
        refreshed = ensure_sdd_initialized(tmp_path)

    assert refreshed == ()
    write_readme.assert_not_called()


def test_ensure_sdd_initialized_refreshes_only_stale_paths(tmp_path: Path) -> None:
    write_sdd_readme(str(tmp_path))
    readme = expected_sdd_readme(str(tmp_path)).path
    readme.write_text("stale\n", encoding="utf-8")

    refreshed = ensure_sdd_initialized(tmp_path)

    assert refreshed == (readme,)
    assert readme.read_text(encoding="utf-8").startswith(
        "# Structured Development Docs"
    )


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_ensure_bare_git_sdd_initialized_commits_only_generated_paths(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _git(None, "init", "--bare", str(bare))
    _git(None, "clone", str(bare), str(repo))
    (repo / "notes.txt").write_text("dirty\n", encoding="utf-8")

    refreshed = ensure_bare_git_sdd_initialized(repo, commit=True, push=True)

    assert repo / "sdd" / "README.md" in refreshed
    status = _git(
        repo, "-c", "color.status=false", "status", "--short"
    ).stdout.splitlines()
    assert status == ["?? notes.txt"]
    commit_message = _git(repo, "log", "-1", "--format=%B").stdout.strip()
    assert commit_message == "Initialize SDD\n\nSASE_TYPE=init"
    committed_paths = _git(
        repo,
        "show",
        "--name-only",
        "--format=",
        "HEAD",
    ).stdout.splitlines()
    assert committed_paths
    assert all(path.startswith("sdd/") for path in committed_paths)
    remote_tree = _git(
        None,
        "--git-dir",
        str(bare),
        "ls-tree",
        "-r",
        "--name-only",
        "HEAD",
    ).stdout.splitlines()
    assert "sdd/README.md" in remote_tree
    assert "notes.txt" not in remote_tree


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_bare_git_sdd_init_recovers_planted_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    generated = tmp_path / "sdd" / "README.md"
    generated.parent.mkdir()
    generated.write_text("guide\n", encoding="utf-8")
    lock_path = tmp_path / ".git" / "index.lock"
    lock_path.touch()
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001")
    monkeypatch.delenv("SASE_SDD_GIT_LOCK_RETRY_DELAYS", raising=False)

    commit_bare_git_sdd_init_paths(tmp_path, [generated], push=False)

    assert not lock_path.exists()
    assert _git(tmp_path, "show", "--format=", "--name-only", "HEAD").stdout == (
        "sdd/README.md\n"
    )
    assert _git(tmp_path, "status", "--porcelain").stdout == ""


def test_commit_bare_git_sdd_init_paths_push_timeout_is_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_SDD_GIT_LOCAL_TIMEOUT", "3")
    monkeypatch.setenv("SASE_SDD_GIT_NETWORK_TIMEOUT", "7")
    generated = tmp_path / "sdd" / "README.md"
    generated.parent.mkdir()
    generated.write_text("guide\n", encoding="utf-8")
    calls: list[tuple[list[str], float | None]] = []

    def git_subcommand(cmd: list[str]) -> str:
        index = 1
        while index + 1 < len(cmd) and cmd[index] == "-c":
            index += 2
        return cmd[index] if index < len(cmd) else ""

    def fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs.get("timeout")))  # type: ignore[arg-type]
        if git_subcommand(cmd) == "diff":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if git_subcommand(cmd) == "push":
            raise subprocess.TimeoutExpired(
                cmd=cmd,
                timeout=kwargs.get("timeout"),
                output="",
                stderr="still running",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    # A push timeout is best-effort: the local commit is preserved and the
    # timeout must not propagate to the caller (which would abort an agent
    # launch via ws_get_workspace_directory).
    with (
        patch("sase.sdd._commit.subprocess.run", side_effect=fake_run),
        patch("sase.sdd._repository_transaction.require_sdd_repository_health"),
    ):
        commit_bare_git_sdd_init_paths(tmp_path, [generated], push=True)

    assert calls[0][1] == 3.0
    assert git_subcommand(calls[-1][0]) == "push"
    assert calls[-1][1] == 7.0
    records = [
        json.loads(line)
        for line in tui_git_ops_jsonl_path().read_text(encoding="utf-8").splitlines()
    ]
    push_timeout = [
        record for record in records if record["operation"] == "bare_git_sdd_init.push"
    ]
    assert push_timeout[-1]["status"] == "timeout"
    assert push_timeout[-1]["timeout_seconds"] == 7.0


def test_commit_bare_git_sdd_init_paths_push_rejection_is_best_effort(
    tmp_path: Path,
) -> None:
    """A non-fast-forward push rejection must not abort the caller.

    Regression: bare-git agent launches call this with push=True and
    raise_on_error=True; a remote-ahead rejection previously propagated and
    failed the launch.
    """
    generated = tmp_path / "sdd" / "README.md"
    generated.parent.mkdir()
    generated.write_text("guide\n", encoding="utf-8")

    def fake_run(
        cmd: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if cmd[:2] == ["git", "push"]:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=cmd,
                output="",
                stderr="! [rejected] HEAD -> master (fetch first)",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    # Must return normally (no exception) despite the rejected push.
    with (
        patch("sase.sdd._commit.subprocess.run", side_effect=fake_run),
        patch("sase.sdd._repository_transaction.require_sdd_repository_health"),
    ):
        commit_bare_git_sdd_init_paths(tmp_path, [generated], push=True)


def test_write_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.yaml"
        plan_file.write_text("steps:\n  - do stuff\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "my_plan", "# My Spec\nDetails here", str(plan_file)
            )

        assert prompt_path.exists()
        assert plan_path.exists()
        assert prompt_path.parent.name == "prompts"
        assert prompt_path.parent.parent.name == "202603"
        assert plan_path.parent.name == "202603"
        prompt_text = prompt_path.read_text(encoding="utf-8")
        prompt_fm, _, _ = parse_frontmatter(prompt_text)
        prompt_link = parse_sdd_artifact_link(prompt_text)
        assert "plan" not in prompt_fm
        assert prompt_link.reference == "../plans/202603/my_plan.md"
        assert prompt_link.target == "../my_plan.md"
        assert prompt_link.body == "# My Spec\nDetails here"
        plan_text = plan_path.read_text(encoding="utf-8")
        assert plan_text.startswith("---\ncreate_time:")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        plan_link = parse_sdd_artifact_link(plan_text)
        assert "prompt" not in plan_fm
        assert plan_link.reference == "plans/202603/prompts/my_plan.md"
        assert plan_link.target == "prompts/my_plan.md"
        assert plan_fm["tier"] == "tale"
        assert "steps:" in plan_text


def test_write_sdd_files_supports_flat_sidecar_plans_root(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Plan\n", encoding="utf-8")
    plans_root = tmp_path / "repo--plans"

    prompt, plan = write_sdd_files(
        plans_root,
        "flat_plan",
        "# Prompt\n",
        str(source),
        plans_root=plans_root,
    )

    assert prompt == plans_root / get_yyyymm() / "prompts" / "flat_plan.md"
    assert plan == plans_root / get_yyyymm() / "flat_plan.md"
    prompt_text = prompt.read_text(encoding="utf-8")
    plan_text = plan.read_text(encoding="utf-8")
    prompt_fm, _, _ = parse_frontmatter(prompt_text)
    plan_fm, _, _ = parse_frontmatter(plan_text)
    assert "plan" not in prompt_fm
    assert "prompt" not in plan_fm
    assert (
        f"- **PLAN:** [../{get_yyyymm()}/flat_plan.md](../flat_plan.md)" in prompt_text
    )
    assert (
        f"- **PROMPT:** [{get_yyyymm()}/prompts/flat_plan.md]"
        "(prompts/flat_plan.md)" in plan_text
    )


def test_write_sdd_files_rebases_seeded_parent_section(tmp_path: Path) -> None:
    from sase.sdd.plan_header_block import (
        PlanHeaderSectionKind,
        parse_plan_header_block,
    )
    from sase.sdd.plan_header_writes import upsert_parent_plan_section

    plans_root = tmp_path / "plans"
    parent = plans_root / "202607" / "parent.md"
    parent.parent.mkdir(parents=True)
    parent.write_text("# Parent\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text(
        upsert_parent_plan_section("# Child\n", "plans:202607/parent.md"),
        encoding="utf-8",
    )

    _prompt, plan = write_sdd_files(
        tmp_path,
        "child",
        "# Prompt\n",
        str(source),
        plans_root=plans_root,
    )

    parsed = parse_plan_header_block(plan.read_text(encoding="utf-8"))
    assert [section.kind for section in parsed.sections] == [
        PlanHeaderSectionKind.PROMPT,
        PlanHeaderSectionKind.PARENT,
    ]
    parent_section = parsed.sections[1]
    assert parent_section.label == "202607/parent.md"
    assert parent_section.target == "parent.md"


def test_write_sdd_spec_does_not_write_plan(tmp_path: Path) -> None:
    sdd_dir = tmp_path / "sdd"

    with patch("sase.sdd.files.get_yyyymm", return_value="202607"):
        prompt_path, plan_path = write_sdd_spec(
            sdd_dir,
            "host_owned_epic",
            "# Planner prompt\n",
        )

    assert prompt_path.is_file()
    assert not plan_path.exists()
    prompt_text = prompt_path.read_text(encoding="utf-8")
    prompt_fm, _, _ = parse_frontmatter(prompt_text)
    prompt_link = parse_sdd_artifact_link(prompt_text)
    assert "plan" not in prompt_fm
    assert prompt_link.reference == "../sdd/plans/202607/host_owned_epic.md"
    assert prompt_link.target == "../host_owned_epic.md"
    assert prompt_link.body == "# Planner prompt\n"


def test_write_sdd_files_missing_plan() -> None:
    """If source plan file doesn't exist, plan_path is not written."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "my_plan", "spec content", "/nonexistent/plan.yaml"
            )
        assert prompt_path.exists()
        assert not plan_path.exists()
        prompt_text = prompt_path.read_text(encoding="utf-8")
        prompt_fm, _, _ = parse_frontmatter(prompt_text)
        prompt_link = parse_sdd_artifact_link(prompt_text)
        assert "plan" not in prompt_fm
        assert prompt_link.reference == "../plans/202603/my_plan.md"
        assert prompt_link.body == "spec content"


def test_write_sdd_files_creates_dirs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "nested" / "sdd"
        plan_file = Path(tmpdir) / "plan.yaml"
        plan_file.write_text("plan", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            write_sdd_files(sdd_dir, "test", "spec", str(plan_file))
        assert (sdd_dir / "plans" / "202603" / "prompts").is_dir()
        assert (sdd_dir / "plans" / "202603").is_dir()


def test_write_sdd_files_epic_tier() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir,
                "my_epic",
                "spec",
                str(plan_file),
                plan_tier="epic",
            )

        assert prompt_path == sdd_dir / "plans" / "202603" / "prompts" / "my_epic.md"
        assert plan_path == sdd_dir / "plans" / "202603" / "my_epic.md"
        assert plan_path.exists()
        prompt_text = prompt_path.read_text(encoding="utf-8")
        plan_text = plan_path.read_text(encoding="utf-8")
        prompt_fm, _, _ = parse_frontmatter(prompt_text)
        plan_fm, _, _ = parse_frontmatter(plan_text)
        assert "plan" not in prompt_fm
        assert "prompt" not in plan_fm
        assert parse_sdd_artifact_link(prompt_text).reference == (
            "../plans/202603/my_epic.md"
        )
        assert parse_sdd_artifact_link(plan_text).reference == (
            "plans/202603/prompts/my_epic.md"
        )
        assert plan_fm["tier"] == "epic"


def test_write_sdd_files_uses_canonical_plan_directory_for_both_tiers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            for plan_tier in ("tale", "epic"):
                write_sdd_files(
                    sdd_dir,
                    f"my_{plan_tier}",
                    "spec",
                    str(plan_file),
                    plan_tier=plan_tier,
                )

        assert (sdd_dir / "plans" / "202603" / "prompts").is_dir()
        assert (sdd_dir / "plans" / "202603" / "my_tale.md").exists()
        assert (sdd_dir / "plans" / "202603" / "my_epic.md").exists()
        assert not (Path(tmpdir) / "plans").exists()
        assert not (sdd_dir / "tales").exists()
        assert not (sdd_dir / "epics").exists()
        assert not (Path(tmpdir) / "prompts").exists()
        assert not (Path(tmpdir) / "specs").exists()


def test_write_sdd_files_rejects_unknown_plan_tier() -> None:
    with pytest.raises(ValueError, match="invalid SDD plan tier"):
        write_sdd_files(Path("/tmp/sdd"), "bad", "spec", "/tmp/plan.md", plan_tier="x")


def test_write_sdd_files_rejects_invalid_cutover_plan_before_writing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("---\ntier: tale\n---\n# Plan\n", encoding="utf-8")
    sdd_dir = tmp_path / "sdd"

    with (
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        pytest.raises(_CommittedPlanValidationError, match="required-missing"),
    ):
        write_sdd_files(sdd_dir, "invalid", "# Prompt\n", str(source))

    assert not (sdd_dir / "plans" / "202608" / "invalid.md").exists()
    assert not (sdd_dir / "plans" / "202608" / "prompts" / "invalid.md").exists()


def test_write_sdd_files_uses_sdd_relative_links() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "linked", "prompt", str(plan_file)
            )

        prompt_text = prompt_path.read_text(encoding="utf-8")
        plan_text = plan_path.read_text(encoding="utf-8")
        prompt_fm, _, _ = parse_frontmatter(prompt_text)
        plan_fm, _, _ = parse_frontmatter(plan_text)
        assert "plan" not in prompt_fm
        assert "prompt" not in plan_fm
        assert (
            "- **PLAN:** [../sdd/plans/202603/linked.md](../linked.md)" in prompt_text
        )
        assert (
            "- **PROMPT:** [sdd/plans/202603/prompts/linked.md]"
            "(prompts/linked.md)" in plan_text
        )


def test_write_sdd_files_uses_local_sase_sdd_relative_links() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "linked", "prompt", str(plan_file)
            )

        prompt_text = prompt_path.read_text(encoding="utf-8")
        plan_text = plan_path.read_text(encoding="utf-8")
        prompt_fm, _, _ = parse_frontmatter(prompt_text)
        plan_fm, _, _ = parse_frontmatter(plan_text)
        assert "plan" not in prompt_fm
        assert "prompt" not in plan_fm
        assert (
            "- **PLAN:** [../.sase/sdd/plans/202603/linked.md](../linked.md)"
            in prompt_text
        )
        assert (
            "- **PROMPT:** [.sase/sdd/plans/202603/prompts/linked.md]"
            "(prompts/linked.md)" in plan_text
        )


def test_write_sdd_files_preserves_existing_plan_frontmatter() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text(
            "---\nbead_id: sase-1y\ntier: epic\nstatus: ready\n---\n# Plan\n",
            encoding="utf-8",
        )

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            _, plan_path = write_sdd_files(
                sdd_dir,
                "preserve",
                "prompt",
                str(plan_file),
                plan_tier="epic",
            )

        plan_text = plan_path.read_text(encoding="utf-8")
        plan_fm, _, _ = parse_frontmatter(plan_text)
        plan_link = parse_sdd_artifact_link(plan_text)
        assert plan_fm["bead_id"] == "sase-1y"
        assert plan_fm["tier"] == "epic"
        assert plan_fm["status"] == "ready"
        assert "prompt" not in plan_fm
        assert plan_link.reference == "sdd/plans/202603/prompts/preserve.md"
        assert plan_link.body == "# Plan\n"


def test_set_frontmatter_fields_is_idempotent() -> None:
    content = "---\nplan: old.md\nkeep: yes\n---\n# Prompt\n"

    once = set_frontmatter_fields(content, {"plan": "new.md"})
    twice = set_frontmatter_fields(once, {"plan": "new.md"})

    assert twice == once
    fm, body, had_frontmatter = parse_frontmatter(twice)
    assert had_frontmatter is True
    assert fm["plan"] == "new.md"
    assert fm["keep"] is True
    assert body == "# Prompt\n"


# ---------------------------------------------------------------------------
# update_prompt_with_qa
# ---------------------------------------------------------------------------


def test_update_prompt_with_qa() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        update_prompt_with_qa(prompt_path, "## Q&A\nQ: Why?\nA: Because.")

        content = prompt_path.read_text(encoding="utf-8")
        assert "Original content" in content
        assert "## Q&A" in content
        assert "Q: Why?" in content


def test_update_prompt_with_qa_preserves_artifact_bullet() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text(
            "- **PLAN:** [../202607/plan.md](../plan.md)\n\nOriginal prompt.\n",
            encoding="utf-8",
        )

        update_prompt_with_qa(
            prompt_path, "### Questions and Answers\n\n#### Q1: Why?\n"
        )

        content = prompt_path.read_text(encoding="utf-8")
        link = parse_sdd_artifact_link(content)
        assert link.reference == "../202607/plan.md"
        assert link.body.startswith("Original prompt.\n")
        assert link.body.count("### Questions and Answers") == 1


def test_update_prompt_with_qa_missing_file() -> None:
    """No-op if prompt file doesn't exist."""
    update_prompt_with_qa(Path("/nonexistent/prompt.md"), "qa content")
    # Should not raise


def test_update_spec_with_qa_legacy_wrapper() -> None:
    """Calling the legacy wrapper twice produces exactly one Q&A block
    (replace-not-append semantics)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        first = "### Questions and Answers\n\n#### Q1: one\n"
        second = "### Questions and Answers\n\n#### Q1: one\n\n#### Q2: two\n"

        update_spec_with_qa(prompt_path, first)
        update_spec_with_qa(prompt_path, second)

        content = prompt_path.read_text(encoding="utf-8")
        assert content.count("### Questions and Answers") == 1
        assert "#### Q1: one" in content
        assert "#### Q2: two" in content
        assert "Original content" in content


def test_set_prompt_qa_replaces_wrapped_block() -> None:
    """A previously-written wrapped Q&A block is replaced cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        initial_qa = (
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n"
            "#### Q1: old\n"
            "%xprompts_enabled:true"
        )
        prompt_path.write_text(f"# Prompt\nBody\n\n{initial_qa}\n", encoding="utf-8")

        new_qa = (
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n"
            "#### Q1: new\n"
            "%xprompts_enabled:true"
        )
        set_prompt_qa(prompt_path, new_qa)

        content = prompt_path.read_text(encoding="utf-8")
        assert content.count("### Questions and Answers") == 1
        assert content.count("%xprompts_enabled:false") == 1
        assert content.count("%xprompts_enabled:true") == 1
        assert "#### Q1: new" in content
        assert "#### Q1: old" not in content
        assert "# Prompt" in content
        assert "Body" in content


def test_set_prompt_qa_strips_legacy_duplicate_blocks() -> None:
    """A snapshot accidentally containing two appended Q&A blocks is
    consolidated to one on the next set_prompt_qa call."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        duplicated = (
            "# Prompt\nBody\n\n"
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n#### Q1: round1\n"
            "%xprompts_enabled:true\n\n"
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n#### Q1: round2\n"
            "%xprompts_enabled:true\n"
        )
        prompt_path.write_text(duplicated, encoding="utf-8")

        merged = (
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n"
            "#### Q1: round1\n\n#### Q2: round2\n"
            "%xprompts_enabled:true"
        )
        set_prompt_qa(prompt_path, merged)

        content = prompt_path.read_text(encoding="utf-8")
        assert content.count("### Questions and Answers") == 1
        assert content.count("%xprompts_enabled:false") == 1
        assert "#### Q1: round1" in content
        assert "#### Q2: round2" in content


def test_set_prompt_qa_missing_file_is_noop() -> None:
    set_prompt_qa(Path("/nonexistent/prompt.md"), "ignored")

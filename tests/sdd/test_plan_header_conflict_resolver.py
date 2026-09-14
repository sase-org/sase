"""Plan-header semantic conflict resolver coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.sdd._plan_header_conflict_resolver import is_plan_header_conflict_path
from sase.sdd._semantic_conflict_resolver import resolve_semantic_conflicts
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
    render_plan_header_block,
)

PLAN_PATH = "202609/a.md"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--initial-branch=master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _write_content(repo: Path, content: str, path: str = PLAN_PATH) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", path)


def _build_rebase_conflict(
    repo: Path,
    *,
    base: str | None,
    local: str,
    upstream: str,
    path: str = PLAN_PATH,
) -> None:
    _init_repo(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    if base is not None:
        _write_content(repo, base, path)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "upstream")
    _write_content(repo, upstream, path)
    _git(repo, "commit", "-m", "upstream")

    _git(repo, "checkout", "master")
    _write_content(repo, local, path)
    _git(repo, "commit", "-m", "local")

    rebase = _git(repo, "rebase", "upstream", check=False)
    assert rebase.returncode != 0


def _plan(
    *sections: PlanHeaderSection,
    frontmatter: str = "tier: tale\n",
    body: str = "# Plan\n\nBody.\n",
) -> str:
    header = render_plan_header_block((_prompt_section(), *sections))
    return f"---\n{frontmatter}---\n\n{header}\n\n{body}"


def _prompt_section() -> PlanHeaderSection:
    return PlanHeaderSection(
        kind=PlanHeaderSectionKind.PROMPT,
        label="prompts/202609/a.md",
        target="../agents/prompts/202609/a.md",
    )


def _agent(label: str, trailing_text: str | None = None) -> PlanHeaderSection:
    return PlanHeaderSection(
        kind=PlanHeaderSectionKind.AGENTS,
        entries=(PlanHeaderEntry(label=label, trailing_text=trailing_text),),
    )


def _commit(sha: str, subject: str) -> PlanHeaderSection:
    return PlanHeaderSection(
        kind=PlanHeaderSectionKind.COMMITS,
        entries=(
            PlanHeaderEntry(
                label=sha[:7],
                target=f"https://example.test/commit/{sha}",
                trailing_text=subject,
            ),
        ),
    )


def _entries(
    document: str,
    kind: PlanHeaderSectionKind,
) -> tuple[PlanHeaderEntry, ...]:
    section = next(
        section
        for section in parse_plan_header_block(document).sections
        if section.kind is kind
    )
    return section.entries


def test_plan_header_conflict_merges_generated_sections_and_stages(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    local_sha = "1" * 40
    upstream_sha = "2" * 40
    _build_rebase_conflict(
        repo,
        base=_plan(),
        local=_plan(
            _agent("local.agent", "local run"),
            _commit(local_sha, "feat: local"),
        ),
        upstream=_plan(
            _agent("upstream.agent", "upstream run"),
            _commit(upstream_sha, "feat: upstream"),
        ),
    )

    result = resolve_semantic_conflicts(repo)

    assert result.ok is True, result.message
    assert result.resolved_files == (PLAN_PATH,)
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout == ""
    merged = (repo / PLAN_PATH).read_text(encoding="utf-8")
    assert [
        entry.label for entry in _entries(merged, PlanHeaderSectionKind.AGENTS)
    ] == [
        "local.agent",
        "upstream.agent",
    ]
    assert [
        entry.trailing_text for entry in _entries(merged, PlanHeaderSectionKind.COMMITS)
    ] == [
        "feat: local",
        "feat: upstream",
    ]
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == PLAN_PATH


def test_plan_header_conflict_prefers_local_metadata_for_duplicate_generated_keys(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = "a" * 40
    _build_rebase_conflict(
        repo,
        base=_plan(),
        local=_plan(
            _agent("shared.agent", "local run"),
            _commit(sha, "feat: local subject"),
        ),
        upstream=_plan(
            _agent("shared.agent", "upstream run"),
            _commit(sha, "feat: upstream subject"),
        ),
    )

    result = resolve_semantic_conflicts(repo)

    assert result.ok is True, result.message
    merged = (repo / PLAN_PATH).read_text(encoding="utf-8")
    agents = _entries(merged, PlanHeaderSectionKind.AGENTS)
    commits = _entries(merged, PlanHeaderSectionKind.COMMITS)
    assert agents == (PlanHeaderEntry(label="shared.agent", trailing_text="local run"),)
    assert commits[0].trailing_text == "feat: local subject"


def test_plan_header_conflict_with_authored_body_difference_fails_closed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo,
        base=_plan(),
        local=_plan(_agent("local.agent"), body="# Plan\n\nLocal body.\n"),
        upstream=_plan(_agent("upstream.agent"), body="# Plan\n\nUpstream body.\n"),
    )

    result = resolve_semantic_conflicts(repo)

    assert result.ok is False
    assert "authored plan conflict remains" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        PLAN_PATH
    )


def test_plan_header_conflict_with_frontmatter_difference_fails_closed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo,
        base=_plan(frontmatter="tier: tale\ngoal: base\n"),
        local=_plan(_agent("local.agent"), frontmatter="tier: tale\ngoal: local\n"),
        upstream=_plan(
            _agent("upstream.agent"),
            frontmatter="tier: tale\ngoal: upstream\n",
        ),
    )

    result = resolve_semantic_conflicts(repo)

    assert result.ok is False
    assert "authored plan conflict remains" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        PLAN_PATH
    )


def test_malformed_plan_header_conflict_is_not_claimed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    malformed = "---\ntier: tale\n---\n\n- **AGENTS:**\n\n# Plan\n"
    _build_rebase_conflict(
        repo,
        base=_plan(),
        local=malformed,
        upstream=_plan(_agent("upstream.agent")),
    )

    result = resolve_semantic_conflicts(repo)

    assert is_plan_header_conflict_path(repo, PLAN_PATH) is False
    assert result.ok is False
    assert result.message == f"non-bead conflicts remain: {PLAN_PATH}"
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        PLAN_PATH
    )


def test_nested_month_prompt_markdown_conflict_is_not_claimed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = "202609/prompts/a.md"
    _build_rebase_conflict(
        repo,
        base="# Prompt\n\nBase\n",
        local="# Prompt\n\nLocal\n",
        upstream="# Prompt\n\nUpstream\n",
        path=path,
    )

    assert is_plan_header_conflict_path(repo, path) is False

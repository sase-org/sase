from __future__ import annotations

from pathlib import Path
import subprocess

from sase.sdd.files import commit_sdd_files
from sase.sdd.referenced_by_doctor import missing_referenced_by_indexes
from sase.workspace_provider.git_exclude import (
    SASE_GIT_INFO_EXCLUDE_PATTERNS,
    ensure_sase_git_info_excludes,
)
from tests._sdd_commit_helpers import init_test_git_repo

_REAL_BLOCK = """# Example

Body

<!-- sase:referenced-by:start -->

## Referenced By

| Agent | Project | Reference | Published | Uses |
| ----- | ------- | --------- | --------- | ---: |
| alice | sase    | plan:x.md | 2026-08-13 |    1 |

<!-- sase:referenced-by:end -->
"""

_FENCED_EXAMPLE = """# Design

```markdown
<!-- sase:referenced-by:start -->

## Referenced By

| Agent | Project | Reference | Published | Uses |
| ----- | ------- | --------- | --------- | ---: |
| alice | sase    | plan:x.md | 2026-08-13 |    1 |

<!-- sase:referenced-by:end -->
```
"""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo_with_excludes(tmp_path: Path) -> Path:
    repo = tmp_path / "plans"
    init_test_git_repo(repo)
    (repo / "README.md").write_text("# Plans\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    ensure_sase_git_info_excludes(str(repo))
    return repo


def test_missing_referenced_by_indexes_fires_on_committed_block_without_json(
    tmp_path: Path,
) -> None:
    repo = _repo_with_excludes(tmp_path)
    document = repo / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    document.write_text(_REAL_BLOCK, encoding="utf-8")
    _git(repo, "add", "202608/example.md")
    _git(repo, "commit", "-q", "-m", "add block")

    assert missing_referenced_by_indexes(repo) == ("202608/example.md",)


def test_missing_referenced_by_indexes_is_silent_when_links_json_is_in_head(
    tmp_path: Path,
) -> None:
    repo = _repo_with_excludes(tmp_path)
    document = repo / "202608" / "example.md"
    index = repo / "links" / "202608" / "example.md.json"
    document.parent.mkdir(parents=True)
    index.parent.mkdir(parents=True)
    document.write_text(_REAL_BLOCK, encoding="utf-8")
    index.write_text('{"schema_version": 1, "rows": []}\n', encoding="utf-8")
    _git(repo, "add", "202608/example.md", "links/202608/example.md.json")
    _git(repo, "commit", "-q", "-m", "add block and index")

    assert missing_referenced_by_indexes(repo) == ()


def test_missing_referenced_by_indexes_ignores_fenced_examples(
    tmp_path: Path,
) -> None:
    repo = _repo_with_excludes(tmp_path)
    document = repo / "202608" / "design.md"
    document.parent.mkdir(parents=True)
    document.write_text(_FENCED_EXAMPLE, encoding="utf-8")
    _git(repo, "add", "202608/design.md")
    _git(repo, "commit", "-q", "-m", "add example")

    assert missing_referenced_by_indexes(repo) == ()


def test_commit_sdd_files_includes_links_index_but_still_excludes_sase(
    tmp_path: Path,
) -> None:
    repo = _repo_with_excludes(tmp_path)
    document = repo / "202608" / "example.md"
    index = repo / "links" / "202608" / "example.md.json"
    ignored = repo / ".sase" / "referenced-by" / "plan" / "202608" / "example.md.json"
    document.parent.mkdir(parents=True)
    index.parent.mkdir(parents=True)
    ignored.parent.mkdir(parents=True)
    document.write_text(_REAL_BLOCK, encoding="utf-8")
    index.write_text('{"schema_version": 1, "rows": []}\n', encoding="utf-8")
    ignored.write_text('{"schema_version": 1, "rows": []}\n', encoding="utf-8")

    assert SASE_GIT_INFO_EXCLUDE_PATTERNS == (".sase/", "/sase/repos/")
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "--", ".sase/referenced-by/plan/x.json"],
            cwd=repo,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "--", "links/202608/example.md.json"],
            cwd=repo,
        ).returncode
        == 1
    )

    assert commit_sdd_files(
        repo,
        "Update artifact link projections",
        paths=[document, index, ignored],
    )
    tracked = set(_git(repo, "ls-files", "-z").stdout.split("\0")) - {""}
    assert "links/202608/example.md.json" in tracked
    assert "202608/example.md" in tracked
    assert not any(path.startswith(".sase/") for path in tracked)

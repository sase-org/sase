from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.ace.patch.archive import get_archive_file_path
from sase.ace.patch.parser import parse_patch_project_file
from sase.external_mirror.pull_requests import (
    MirrorPassResult,
    run_pull_request_mirror_pass,
)
from sase.vcs_provider import PullRequestListState, PullRequestWire


class _Provider:
    def __init__(self, pull_requests: list[PullRequestWire]) -> None:
        self.pull_requests = pull_requests
        self.calls: list[tuple[str, int]] = []

    def list_pull_requests(
        self,
        cwd: str,
        state: PullRequestListState = "open",
        limit: int = 100,
    ) -> list[PullRequestWire]:
        del cwd
        self.calls.append((state, limit))
        return list(self.pull_requests)


def _pr(
    number: int,
    *,
    title: str = "Fix bug",
    state: str = "open",
    body: str = "",
    is_draft: bool = False,
    merged_at: str = "",
    updated_at: str | None = None,
    author: str = "alice",
) -> PullRequestWire:
    timestamp = updated_at or f"2026-08-10T12:{number:02d}:00Z"
    return PullRequestWire(
        number=number,
        title=title,
        state=state,  # type: ignore[arg-type]
        provider_id=f"gh:{number}",
        url=f"https://github.com/org/repo/pull/{number}",
        body=body,
        is_draft=is_draft,
        author=author,
        head_ref=f"branch-{number}",
        updated_at=timestamp,
        merged_at=merged_at,
    )


def _run(
    tmp_path: Path,
    pull_requests: list[PullRequestWire],
    *,
    project_file: Path | None = None,
    dry_run: bool = False,
    full: bool = False,
) -> tuple[_Provider, MirrorPassResult]:
    active = project_file or tmp_path / "proj.sase"
    active.touch()
    provider = _Provider(pull_requests)
    result = run_pull_request_mirror_pass(
        project="proj",
        project_file=str(active),
        workspace_dir=str(tmp_path),
        state_dir=tmp_path / "state",
        dry_run=dry_run,
        full=full,
        now=datetime(2026, 8, 10, 13, tzinfo=UTC),
        supports_pull_requests_fn=lambda _cwd: True,
        provider_factory=lambda _cwd: provider,
    )
    return provider, result


def test_mirror_repairs_crash_window_reserved_stub(tmp_path: Path) -> None:
    active = tmp_path / "proj.sase"
    active.write_text("NAME: proj_fix_1\nSTATUS: Reserved\n", encoding="utf-8")

    _, result = _run(
        tmp_path,
        [_pr(1, body="Body\n\nSASE_PATCH=proj_fix_1")],
        project_file=active,
    )

    assert result.repaired == 1
    patches = parse_patch_project_file(str(active))
    assert [patch.name for patch in patches] == ["proj_fix_1"]
    assert patches[0].pr_origin == "sase"
    assert patches[0].pr_url == "https://github.com/org/repo/pull/1"


def test_mirror_imports_statuses_to_active_and_archive(tmp_path: Path) -> None:
    active = tmp_path / "proj.sase"
    prs = [
        _pr(1, title="Draft PR", is_draft=True),
        _pr(2, title="Ready PR"),
        _pr(3, title="Merged PR", state="closed", merged_at="2026-08-10T13:00:00Z"),
        _pr(4, title="Closed PR", state="closed"),
    ]

    _, result = _run(tmp_path, prs, project_file=active)

    assert result.imported == 4
    active_statuses = {patch.status for patch in parse_patch_project_file(str(active))}
    archive_statuses = {
        patch.status
        for patch in parse_patch_project_file(get_archive_file_path(str(active)))
    }
    assert active_statuses == {"Draft", "Mailed"}
    assert archive_statuses == {"Submitted", "Archived"}


def test_mirror_dry_run_plans_exact_names_without_mutating(tmp_path: Path) -> None:
    active = tmp_path / "proj.sase"
    active.write_text("NAME: proj_fix_bug_1\nSTATUS: Draft\n", encoding="utf-8")

    _, result = _run(
        tmp_path,
        [_pr(1, title="Fix bug")],
        project_file=active,
        dry_run=True,
    )

    assert result.imported == 1
    assert result.planned[0].patch_name == "proj_fix_bug_2"
    assert active.read_text(encoding="utf-8") == "NAME: proj_fix_bug_1\nSTATUS: Draft\n"
    cursor = tmp_path / "state" / "external_mirror" / "pull_requests" / "proj.json"
    assert not cursor.exists()


def test_mirror_budget_defers_remaining_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.external_mirror.pull_requests as mirror

    monkeypatch.setattr(mirror, "_MAX_IMPORTS_PER_PASS", 1)

    _, result = _run(tmp_path, [_pr(1), _pr(2), _pr(3)])

    assert result.imported == 1
    assert result.deferred == 2
    assert result.reason == "deferred"


def test_mirror_author_filter(tmp_path: Path) -> None:
    from sase.external_mirror.config import ExternalMirrorConfig
    from sase.external_mirror.pull_requests import run_pull_request_mirror_pass

    active = tmp_path / "proj.sase"
    active.touch()
    provider = _Provider([_pr(1, author="alice"), _pr(2, author="bob")])
    result = run_pull_request_mirror_pass(
        project="proj",
        project_file=str(active),
        workspace_dir=str(tmp_path),
        state_dir=tmp_path / "state",
        config=ExternalMirrorConfig(pr_authors=("bob",)),
        now=datetime(2026, 8, 10, 13, tzinfo=UTC),
        supports_pull_requests_fn=lambda _cwd: True,
        provider_factory=lambda _cwd: provider,
    )

    assert result.imported == 1
    patches = parse_patch_project_file(str(active))
    assert len(patches) == 1
    assert patches[0].pr_url == "https://github.com/org/repo/pull/2"


def test_mirror_url_variance_does_not_duplicate(tmp_path: Path) -> None:
    active = tmp_path / "proj.sase"
    active.write_text(
        "NAME: proj_existing_1\n"
        "DESCRIPTION:\n"
        "  Existing\n"
        "PR: https://github.com/org/repo/pull/1\n"
        "PR_ORIGIN: external\n"
        "STATUS: Mailed\n",
        encoding="utf-8",
    )
    varied = replace(
        _pr(1),
        url="http://www.github.com/ORG/REPO.git/pull/1/?x=1#frag",
    )

    _, result = _run(tmp_path, [varied], project_file=active)

    assert result.skipped == 1
    assert len(parse_patch_project_file(str(active))) == 1

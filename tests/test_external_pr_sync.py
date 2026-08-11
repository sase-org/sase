"""External PR mirror sync engine coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sase.ace.patch.importer import project_patch_files
from sase.core.external_pr_wire import PR_ORIGIN_EXTERNAL
from sase.external_mirror.pr_sync import KIND, sync_external_pull_requests
from sase.external_mirror.state import (
    MirrorCursor,
    read_backoff_state,
    read_mirror_cursor,
    write_mirror_cursor,
)
from sase.vcs_provider import PullRequestWire


class _Provider:
    def __init__(self, pull_requests: list[PullRequestWire]) -> None:
        self.pull_requests = pull_requests
        self.limits: list[int] = []

    def list_pull_requests(
        self,
        cwd: str,
        state: str = "open",
        limit: int = 100,
    ) -> list[PullRequestWire]:
        del cwd, state
        self.limits.append(limit)
        return self.pull_requests if limit <= 0 else self.pull_requests[:limit]


class _FailingProvider:
    def list_pull_requests(
        self,
        cwd: str,
        state: str = "open",
        limit: int = 100,
    ) -> list[PullRequestWire]:
        del cwd, state, limit
        raise RuntimeError("auth failed")


def _pr(
    number: int,
    updated_at: str,
    *,
    merged: bool = False,
    author: str = "",
) -> PullRequestWire:
    return PullRequestWire(
        number=number,
        title=f"Feature {number}",
        state="closed" if merged else "open",
        provider_id=f"PR_{number}",
        url=f"https://github.com/acme/widget/pull/{number}",
        body="Body",
        author=author,
        updated_at=updated_at,
        merged_at="2026-08-03T00:00:00Z" if merged else "",
    )


def _malformed_pr() -> PullRequestWire:
    return PullRequestWire(
        number=99,
        title="Malformed",
        state="open",
        provider_id="PR_bad",
        url="not a pull request url",
        body="Body",
        updated_at="2026-08-02T00:00:00Z",
    )


def _workspace_project(project: str) -> None:
    active_file, _ = project_patch_files(project)
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    Path(active_file).write_text("", encoding="utf-8")


def test_budget_exhaustion_defers_without_advancing_cursor(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests", lambda _: True
    )
    _workspace_project("proj")
    provider = _Provider(
        [
            _pr(1, "2026-08-02T00:00:00Z"),
            _pr(2, "2026-08-02T00:01:00Z"),
        ]
    )

    report = sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=provider,
        now=datetime(2026, 8, 3, tzinfo=UTC),
        create_budget=1,
    )

    assert report.created == 1
    assert report.budget_exhausted == 1
    assert read_mirror_cursor(tmp_path, KIND, "proj") == MirrorCursor()


def test_malformed_provider_pr_defers_cursor_and_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests",
        lambda _: True,
    )
    active_file, _ = project_patch_files("proj")
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    Path(active_file).write_text("", encoding="utf-8")

    report = sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=_Provider([_malformed_pr()]),
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert report.errors == 1
    assert report.error_details == ["PR_bad: invalid_pull_request_url"]
    assert Path(active_file).read_text(encoding="utf-8") == ""
    assert read_mirror_cursor(tmp_path, KIND, "proj") == MirrorCursor()


def test_provider_error_records_backoff_and_deletes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests", lambda _: True
    )
    active_file, _ = project_patch_files("proj")
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    Path(active_file).write_text("NAME: keep\nSTATUS: WIP\n", encoding="utf-8")

    report = sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=_FailingProvider(),
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert report.errors == 1
    assert "NAME: keep" in Path(active_file).read_text(encoding="utf-8")
    assert read_backoff_state(tmp_path, KIND)["proj"].last_error == "auth failed"


def test_dry_run_writes_nothing_and_does_not_advance_cursor(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests", lambda _: True
    )
    active_file, _ = project_patch_files("proj")
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    Path(active_file).write_text("", encoding="utf-8")

    report = sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=_Provider([_pr(1, "2026-08-02T00:00:00Z")]),
        now=datetime(2026, 8, 3, tzinfo=UTC),
        dry_run=True,
    )

    assert report.created == 1
    assert Path(active_file).read_text(encoding="utf-8") == ""
    assert read_mirror_cursor(tmp_path, KIND, "proj") == MirrorCursor()


def test_daily_repair_scan_forces_unbounded_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests", lambda _: True
    )
    _workspace_project("proj")
    write_mirror_cursor(
        tmp_path,
        KIND,
        "proj",
        MirrorCursor(
            last_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
            last_provider_id="PR_0",
            backfill_complete=True,
            last_full_scan_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )
    provider = _Provider([_pr(1, "2026-08-02T00:00:00Z")])

    sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=provider,
        now=datetime(2026, 8, 3, 1, tzinfo=UTC),
        fetch_limit=1,
    )

    assert provider.limits == [0]


def test_incremental_window_skips_strictly_old_records(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests", lambda _: True
    )
    active_file, _ = project_patch_files("proj")
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    Path(active_file).write_text("", encoding="utf-8")
    write_mirror_cursor(
        tmp_path,
        KIND,
        "proj",
        MirrorCursor(
            last_updated_at=datetime(2026, 8, 3, tzinfo=UTC),
            last_provider_id="PR_0",
            backfill_complete=True,
            last_full_scan_at=datetime(2026, 8, 3, tzinfo=UTC) - timedelta(hours=1),
        ),
    )

    report = sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=_Provider([_pr(1, "2026-08-02T23:49:59Z")]),
        now=datetime(2026, 8, 3, 1, tzinfo=UTC),
    )

    assert report.seen == 1
    assert PR_ORIGIN_EXTERNAL not in Path(active_file).read_text(encoding="utf-8")


def test_pr_authors_narrows_adoption_case_insensitively(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests", lambda _: True
    )
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.mirrored_pr_authors", lambda: frozenset({"bob"})
    )
    active_file, _ = project_patch_files("proj")
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    Path(active_file).write_text("", encoding="utf-8")

    report = sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=_Provider(
            [
                _pr(1, "2026-08-02T00:00:00Z", author="alice"),
                _pr(2, "2026-08-02T00:00:01Z", author="BOB"),
            ]
        ),
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert report.fetched == 2
    assert report.unmirrored == 1
    assert report.created == 1
    body = Path(active_file).read_text(encoding="utf-8")
    assert "https://github.com/acme/widget/pull/2" in body
    assert "https://github.com/acme/widget/pull/1" not in body


def test_pr_authors_empty_by_default_adopts_every_author(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.supports_pull_requests", lambda _: True
    )
    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.mirrored_pr_authors", lambda: frozenset()
    )
    _workspace_project("proj")

    report = sync_external_pull_requests(
        project_key="proj",
        workspace_dir="/repo",
        state_dir=tmp_path,
        provider=_Provider(
            [
                _pr(1, "2026-08-02T00:00:00Z", author="alice"),
                _pr(2, "2026-08-02T00:00:01Z", author="bob"),
            ]
        ),
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert report.unmirrored == 0
    assert report.created == 2

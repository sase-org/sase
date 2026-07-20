"""Tests for ACE update toast content."""

from __future__ import annotations

from sase.ace.tui.actions import update_toast
from sase.updates import (
    CommitSourceSpec,
    CommitSummary,
    IncomingCommits,
    OutdatedComponent,
    UpdateStatus,
)

from tests.ace.tui._update_toast_helpers import (
    _editable_component,
    _incoming,
    _status,
)


def test_update_toast_message_recommends_update_keymap() -> None:
    message = update_toast._format_update_toast_message(_status())

    assert "2 updates" in message
    assert "sase" in message
    assert "1.0.0 → 1.1.0" in message
    assert "],U[/]" in message
    assert "update sase, core & plugins" in message


def test_update_toast_message_lists_all_component_headers() -> None:
    message = update_toast._format_update_toast_message(_status(count=4))

    assert "…and 1 more" not in message
    assert "nvim" in message
    assert "0.3.0 → 0.4.0" in message


def test_build_toast_commit_sections_fetches_git_before_github() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase",
            ),
            _editable_component("github"),
        ),
    )
    calls: list[str] = []

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        calls.append(f"{spec.source}:{spec.repo_full_name}")
        assert limit == 20
        assert offline is False
        if spec.source == "git":
            return IncomingCommits(
                total=1,
                commits=(CommitSummary("abc1234", "plugin change"),),
                source="git",
            )
        return IncomingCommits(
            total=1,
            commits=(CommitSummary("def5678", "host change"),),
            source="github",
        )

    sections = update_toast._build_toast_commit_sections(
        status.components,
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=10**12,
    )

    assert calls == ["git:github", "github:sase-org/sase"]
    assert [section.label for section in sections] == ["sase", "github"]
    assert sections[0].commits[0].subject == "host change"
    assert sections[1].commits[0].subject == "plugin change"


def test_update_toast_message_renders_grouped_commits_and_overflow() -> None:
    status = _status(count=1)
    sections = (
        update_toast._ToastRepoSection(
            label="sase",
            installed_version="1.0.0",
            latest_version="1.1.0",
            commits=(
                CommitSummary("abc1234", "fix: escape [toast] markup"),
                CommitSummary("def5678", ""),
            ),
            total=3,
        ),
    )

    message = update_toast._format_update_toast_message(status, sections)

    assert "1 update" in message
    assert "↑ sase" in message
    assert "1.0.0 → 1.1.0" in message
    assert "abc1234" in message
    assert "fix: escape \\[toast] markup" in message
    assert "def5678" in message
    assert "+1 more…" in message
    assert message.endswith("update sase, core & plugins")


def test_build_toast_commit_sections_fairly_truncates_to_global_budget() -> None:
    components = (
        _editable_component("sase", role="host"),
        _editable_component("github"),
    )

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        del limit, offline
        return _incoming(spec.repo_full_name[:1], 20)

    sections = update_toast._build_toast_commit_sections(
        components,
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=10**12,
    )

    assert [len(section.commits) for section in sections] == [10, 10]
    assert [section.total for section in sections] == [20, 20]
    message = update_toast._format_update_toast_message(
        UpdateStatus(checked_at=100.0, components=components),
        sections,
    )
    assert message.count("+10 more…") == 2


def test_build_toast_commit_sections_degrades_to_header_only() -> None:
    components = (
        _editable_component("github"),
        OutdatedComponent(
            display_name="telegram",
            role="plugin",
            installed_version="0.1.0",
            latest_version="0.2.0",
            distribution_name="sase-telegram",
        ),
    )

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        del spec, limit, offline
        return IncomingCommits(0, (), "unavailable", error="offline")

    sections = update_toast._build_toast_commit_sections(
        components,
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=10**12,
    )

    assert [section.label for section in sections] == ["github", "telegram"]
    assert [section.total for section in sections] == [0, 0]
    assert all(not section.commits for section in sections)
    message = update_toast._format_update_toast_message(
        UpdateStatus(checked_at=100.0, components=components),
        sections,
    )
    assert "offline" not in message
    assert "github" in message
    assert "telegram" in message


def test_build_toast_commit_sections_skips_fetch_after_deadline() -> None:
    calls = 0

    def fake_fetch(
        spec: CommitSourceSpec,
        *,
        limit: int,
        offline: bool,
    ) -> IncomingCommits:
        nonlocal calls
        del spec, limit, offline
        calls += 1
        return _incoming("x", 1)

    sections = update_toast._build_toast_commit_sections(
        (_editable_component("github"),),
        fetch_fn=fake_fetch,
        max_total=20,
        offline=False,
        deadline=0.0,
    )

    assert calls == 0
    assert sections[0].label == "github"
    assert sections[0].total == 0
    assert sections[0].commits == ()

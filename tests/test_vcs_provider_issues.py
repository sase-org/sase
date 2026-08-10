"""Tests for the optional issue-tracker VCS provider seam."""

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pluggy
import pytest

from sase.vcs_provider import IssueWire
from sase.vcs_provider._hookspec import VCSHookSpec, hookimpl
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin
from sase.vcs_provider.testing import FakeIssueProvider


def _manager(*plugins: object) -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        pm.register(plugin)
    return VCSPluginManager(pm)


def _issue(number: int, state: str = "open") -> IssueWire:
    return IssueWire(
        number=number,
        title=f"Issue {number}",
        state=state,  # type: ignore[arg-type]
        updated_at=f"2026-07-{number:02d}T00:00:00Z",
        url=f"https://example.test/issues/{number}",
    )


def test_issue_wire_is_frozen_and_uses_immutable_collections() -> None:
    issue = IssueWire(
        number=7,
        title="Frozen",
        state="open",
        labels=("bug",),
        assignees=("octocat",),
    )

    assert issue.labels == ("bug",)
    with pytest.raises(FrozenInstanceError):
        issue.title = "changed"  # type: ignore[misc]


def test_issue_wire_provider_id_defaults_empty_and_round_trips() -> None:
    assert IssueWire(number=1, title="Untagged", state="open").provider_id == ""
    assert (
        IssueWire(
            number=1, title="Tagged", state="open", provider_id="I_kwDOabc123"
        ).provider_id
        == "I_kwDOabc123"
    )


def test_complete_fake_provider_reports_capability() -> None:
    provider = _manager(FakeIssueProvider())

    assert provider.supports_issues() is True


def test_bare_git_and_empty_manager_do_not_report_issue_capability() -> None:
    assert _manager().supports_issues() is False
    assert _manager(BareGitPlugin()).supports_issues() is False


def test_partial_issue_plugin_does_not_report_capability() -> None:
    class PartialPlugin:
        @hookimpl
        def vcs_list_issues(
            self, cwd: str, state: str = "open", limit: int = 100
        ) -> list[IssueWire]:
            return []

    assert _manager(PartialPlugin()).supports_issues() is False


def test_split_issue_capability_probes_report_independently() -> None:
    class ListingOnlyPlugin:
        @hookimpl
        def vcs_list_issues(
            self, cwd: str, state: str = "open", limit: int = 100
        ) -> list[IssueWire]:
            return []

    provider = _manager(ListingOnlyPlugin())

    assert provider.supports_issue_listing() is True
    assert provider.supports_issue_reads() is False
    assert provider.supports_issue_mutations() is False
    assert provider.supports_issues() is False


def test_complete_fake_provider_reports_every_split_capability() -> None:
    provider = _manager(FakeIssueProvider())

    assert provider.supports_issue_listing() is True
    assert provider.supports_issue_reads() is True
    assert provider.supports_issue_mutations() is True


def test_fake_provider_lists_filters_and_limits_issues() -> None:
    provider = _manager(FakeIssueProvider([_issue(1), _issue(2, "closed"), _issue(3)]))

    assert [issue.number for issue in provider.list_issues("/repo")] == [3, 1]
    assert [
        issue.number
        for issue in provider.list_issues("/repo", state="closed", limit=10)
    ] == [2]
    assert [
        issue.number for issue in provider.list_issues("/repo", state="all", limit=2)
    ] == [3, 2]
    assert len(provider.list_issues("/repo", state="all", limit=0)) == 3


def test_fake_provider_crud_round_trip() -> None:
    timestamps = iter(["2026-07-15T10:00:00Z", "2026-07-15T11:00:00Z"])
    plugin = FakeIssueProvider(clock=lambda: next(timestamps))
    provider = _manager(plugin)

    created = provider.create_issue(
        "New issue", "Original body", ["bug", "p1"], "/repo"
    )

    assert created == IssueWire(
        number=1,
        title="New issue",
        state="open",
        body="Original body",
        labels=("bug", "p1"),
        author="test-user",
        created_at="2026-07-15T10:00:00Z",
        updated_at="2026-07-15T10:00:00Z",
        url="https://example.test/issues/1",
    )
    assert provider.get_issue(1, "/repo") is created

    updated = provider.update_issue(
        1,
        "/repo",
        title="",
        body="Updated body",
        state="closed",
        labels=[],
    )

    assert updated.title == ""
    assert updated.body == "Updated body"
    assert updated.state == "closed"
    assert updated.labels == ()
    assert updated.created_at == created.created_at
    assert updated.updated_at == "2026-07-15T11:00:00Z"
    assert provider.get_issue_url(1, "/repo") == created.url
    assert plugin.issues == (updated,)


def test_fake_provider_missing_issue_raises_key_error() -> None:
    provider = _manager(FakeIssueProvider())

    with pytest.raises(KeyError, match="#404"):
        provider.get_issue(404, "/repo")
    with pytest.raises(KeyError, match="#404"):
        provider.update_issue(404, "/repo", state="closed")


def test_unimplemented_issue_operations_raise_not_implemented() -> None:
    provider = _manager()

    with pytest.raises(NotImplementedError, match="list_issues"):
        provider.list_issues("/repo")
    with pytest.raises(NotImplementedError, match="get_issue_url"):
        provider.get_issue_url(1, "/repo")


@patch("sase.vcs_provider._registry.get_vcs_provider")
def test_registry_capability_probe_uses_selected_provider(mock_get: MagicMock) -> None:
    from sase.vcs_provider._registry import supports_issues

    provider = _manager(FakeIssueProvider())
    mock_get.return_value = provider

    assert supports_issues("/repo") is True
    mock_get.assert_called_once_with("/repo")


@patch("sase.vcs_provider._registry.get_vcs_provider")
def test_registry_split_issue_capability_probes_use_selected_provider(
    mock_get: MagicMock,
) -> None:
    from sase.vcs_provider._registry import (
        supports_issue_listing,
        supports_issue_mutations,
        supports_issue_reads,
    )

    mock_get.return_value = _manager(FakeIssueProvider(capabilities=["issue_listing"]))

    assert supports_issue_listing("/repo") is True
    assert supports_issue_reads("/repo") is False
    assert supports_issue_mutations("/repo") is False


def test_fake_provider_capabilities_restrict_exposed_operations() -> None:
    provider = _manager(FakeIssueProvider(capabilities=["issue_listing"]))

    assert provider.supports_issue_listing() is True
    assert provider.supports_issue_reads() is False
    assert provider.supports_issue_mutations() is False
    assert provider.supports_pull_requests() is False
    with pytest.raises(NotImplementedError, match="get_issue"):
        provider.get_issue(1, "/repo")


def test_fake_provider_capabilities_default_to_full_support() -> None:
    provider = _manager(FakeIssueProvider())

    assert provider.supports_issue_listing() is True
    assert provider.supports_issue_reads() is True
    assert provider.supports_issue_mutations() is True
    assert provider.supports_pull_requests() is True

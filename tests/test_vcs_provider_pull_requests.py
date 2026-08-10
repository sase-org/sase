"""Tests for the optional pull-request VCS provider seam."""

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pluggy
import pytest

from sase.vcs_provider import PullRequestWire
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


def _pull_request(
    number: int, state: str = "open", merged_at: str = ""
) -> PullRequestWire:
    return PullRequestWire(
        number=number,
        title=f"PR {number}",
        state=state,  # type: ignore[arg-type]
        updated_at=f"2026-07-{number:02d}T00:00:00Z",
        url=f"https://example.test/pull/{number}",
        merged_at=merged_at,
    )


def test_pull_request_wire_is_frozen() -> None:
    pull_request = PullRequestWire(
        number=9,
        title="Frozen",
        state="open",
        head_ref="feature",
        base_ref="main",
    )

    assert pull_request.head_ref == "feature"
    with pytest.raises(FrozenInstanceError):
        pull_request.title = "changed"  # type: ignore[misc]


def test_pull_request_wire_defaults_are_empty_and_not_draft() -> None:
    pull_request = PullRequestWire(number=1, title="Minimal", state="open")

    assert pull_request.provider_id == ""
    assert pull_request.url == ""
    assert pull_request.body == ""
    assert pull_request.is_draft is False
    assert pull_request.author == ""
    assert pull_request.head_ref == ""
    assert pull_request.base_ref == ""
    assert pull_request.closed_at == ""
    assert pull_request.merged_at == ""


def test_complete_fake_provider_reports_pull_request_capability() -> None:
    provider = _manager(FakeIssueProvider())

    assert provider.supports_pull_requests() is True


def test_bare_git_and_empty_manager_do_not_report_pull_request_capability() -> None:
    assert _manager().supports_pull_requests() is False
    assert _manager(BareGitPlugin()).supports_pull_requests() is False


def test_partial_pull_request_plugin_reports_capability_independent_of_issues() -> None:
    class PullRequestOnlyPlugin:
        @hookimpl
        def vcs_list_pull_requests(
            self, cwd: str, state: str = "open", limit: int = 100
        ) -> list[PullRequestWire]:
            return []

    provider = _manager(PullRequestOnlyPlugin())

    assert provider.supports_pull_requests() is True
    assert provider.supports_issues() is False


def test_fake_provider_lists_filters_and_limits_pull_requests() -> None:
    provider = _manager(
        FakeIssueProvider(
            pull_requests=[
                _pull_request(1),
                _pull_request(2, "closed"),
                _pull_request(3),
                _pull_request(4, "closed", merged_at="2026-07-04T00:00:00Z"),
            ]
        )
    )

    assert [pr.number for pr in provider.list_pull_requests("/repo")] == [3, 1]
    assert [
        pr.number
        for pr in provider.list_pull_requests("/repo", state="closed", limit=10)
    ] == [4, 2]
    assert [
        pr.number for pr in provider.list_pull_requests("/repo", state="all", limit=2)
    ] == [4, 3]
    assert len(provider.list_pull_requests("/repo", state="all", limit=0)) == 4

    merged = next(
        pr
        for pr in provider.list_pull_requests("/repo", state="all", limit=0)
        if pr.number == 4
    )
    assert merged.merged_at == "2026-07-04T00:00:00Z"


def test_fake_provider_pull_requests_property_returns_stable_snapshot() -> None:
    plugin = FakeIssueProvider(pull_requests=[_pull_request(2), _pull_request(1)])

    assert [pr.number for pr in plugin.pull_requests] == [1, 2]


def test_fake_provider_duplicate_pull_request_number_raises_value_error() -> None:
    with pytest.raises(ValueError, match="duplicate pull request number"):
        FakeIssueProvider(pull_requests=[_pull_request(1), _pull_request(1)])


def test_unimplemented_pull_request_operations_raise_not_implemented() -> None:
    provider = _manager()

    with pytest.raises(NotImplementedError, match="list_pull_requests"):
        provider.list_pull_requests("/repo")


@patch("sase.vcs_provider._registry.get_vcs_provider")
def test_registry_pull_request_capability_probe_uses_selected_provider(
    mock_get: MagicMock,
) -> None:
    from sase.vcs_provider._registry import supports_pull_requests

    provider = _manager(FakeIssueProvider())
    mock_get.return_value = provider

    assert supports_pull_requests("/repo") is True
    mock_get.assert_called_once_with("/repo")


def test_fake_provider_capabilities_can_disable_pull_requests_only() -> None:
    provider = _manager(
        FakeIssueProvider(
            pull_requests=[_pull_request(1)],
            capabilities=["issue_listing", "issue_reads", "issue_mutations"],
        )
    )

    assert provider.supports_issues() is True
    assert provider.supports_pull_requests() is False
    with pytest.raises(NotImplementedError, match="list_pull_requests"):
        provider.list_pull_requests("/repo")

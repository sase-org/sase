"""Tests for the hosted agent-page metadata lane."""

from __future__ import annotations

from io import StringIO
from unittest.mock import Mock

import pytest
from rich.console import Console

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_page_url import (
    agent_publishes_page,
    resolve_agent_page_url,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    build_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_AGENT_PAGE_URL = (
    "https://github.com/acme/widgets--agents/blob/main/"
    "agents/alice.athena.worker/README.md"
)
_META_COMMITS = [
    {
        "message": "feat: finish the work",
        "sha": "1234567890abcdef",
        "cwd": "/tmp/widgets_7",
    }
]


def _committed_agent(**overrides: object) -> Agent:
    values: dict[str, object] = {
        "status": "DONE",
        "agent_name": "worker",
        "project_file": "/projects/widgets/widgets.sase",
        "workspace_dir": "/tmp/widgets_7",
        "step_output": {"meta_commits": _META_COMMITS},
    }
    values.update(overrides)
    return make_agent(**values)


def _stub_hosted_resolver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    url: str | None = _AGENT_PAGE_URL,
) -> tuple[Mock, Mock, Mock]:
    store = object()
    resolver = Mock()
    resolver.agent_url.return_value = url
    resolve_store = Mock(return_value=store)
    hosted_resolver = Mock(return_value=resolver)
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_page_url.resolve_sdd_store",
        resolve_store,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_page_url.hosted_link_resolver",
        hosted_resolver,
    )
    return resolve_store, hosted_resolver, resolver


def test_done_agent_with_commits_renders_resolved_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_page_url.parse_workspace_dir",
        lambda _project_file: "/projects/widgets",
    )
    _stub_hosted_resolver(monkeypatch)
    agent = _committed_agent()

    summary = build_detail_header_summary(agent)
    header, _ = build_header_text(agent, summary=summary)

    assert f"Page: {_AGENT_PAGE_URL}\n" in header.plain


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "RUNNING"},
        {"step_output": {"meta_commits": []}},
        {"is_clan_container": True},
    ],
    ids=["running", "no-commits", "clan-container"],
)
def test_page_predicate_hides_ineligible_agents(overrides: dict[str, object]) -> None:
    assert agent_publishes_page(_committed_agent(**overrides)) is False


def test_page_lane_hidden_when_resolution_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_page_url.parse_workspace_dir",
        lambda _project_file: "/projects/widgets",
    )
    _stub_hosted_resolver(monkeypatch, url=None)
    agent = _committed_agent()

    summary = build_detail_header_summary(agent)
    header, _ = build_header_text(agent, summary=summary)

    assert summary.agent_page_url is None
    assert "Page: " not in header.plain


def test_plan_done_agent_with_commits_publishes_page() -> None:
    assert agent_publishes_page(_committed_agent(status="PLAN DONE")) is True


def test_page_lane_appears_after_name_and_before_project_fields() -> None:
    agent = _committed_agent()
    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(agent_page_url=_AGENT_PAGE_URL),
    )

    assert header.plain.index("Name: ") < header.plain.index("Page: ")
    assert header.plain.index("Page: ") < header.plain.index("ChangeSpec: ")


def test_page_lane_ellipsizes_without_losing_logical_url() -> None:
    header, _ = build_header_text(
        _committed_agent(),
        summary=DetailHeaderSummary(agent_page_url=_AGENT_PAGE_URL),
    )
    output = StringIO()
    console = Console(
        file=output,
        width=40,
        force_terminal=False,
        color_system=None,
    )

    console.print(header, end="")

    page_lines = [
        line for line in output.getvalue().splitlines() if line.startswith("Page: ")
    ]
    assert len(page_lines) == 1
    assert page_lines[0].endswith("…")
    assert _AGENT_PAGE_URL in header.plain


def test_resolve_agent_page_url_requires_project_file() -> None:
    assert resolve_agent_page_url(_committed_agent(project_file="")) is None


def test_resolve_agent_page_url_requires_primary_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_page_url.parse_workspace_dir",
        lambda _project_file: None,
    )
    agent = _committed_agent(workspace_dir=None)

    assert resolve_agent_page_url(agent) is None


@pytest.mark.parametrize("raising_boundary", ["store", "agent-url"])
def test_resolve_agent_page_url_swallows_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
    raising_boundary: str,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_page_url.parse_workspace_dir",
        lambda _project_file: "/projects/widgets",
    )
    resolve_store, _hosted_resolver, resolver = _stub_hosted_resolver(monkeypatch)
    if raising_boundary == "store":
        resolve_store.side_effect = RuntimeError("store unavailable")
    else:
        resolver.agent_url.side_effect = RuntimeError("remote unavailable")

    assert resolve_agent_page_url(_committed_agent()) is None


def test_resolve_agent_page_url_anchors_on_stable_primary_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stable_root = "/projects/widgets"
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_page_url.parse_workspace_dir",
        lambda _project_file: stable_root,
    )
    resolve_store, hosted_resolver, resolver = _stub_hosted_resolver(monkeypatch)
    agent = _committed_agent(workspace_dir="/workspaces/widgets_27")

    assert resolve_agent_page_url(agent) == _AGENT_PAGE_URL
    resolve_store.assert_called_once_with(stable_root, 1)
    hosted_resolver.assert_called_once_with(
        resolve_store.return_value,
        project="widgets",
        primary_root=stable_root,
    )
    resolver.snapshot_agent_name_registry.assert_called_once_with()
    resolver.agent_url.assert_called_once_with("worker")


def test_summary_can_skip_agent_page_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_page = Mock(side_effect=AssertionError("resolver should be skipped"))
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary.resolve_agent_page_url",
        resolve_page,
    )

    summary = build_detail_header_summary(
        _committed_agent(),
        include_agent_page_url=False,
    )

    assert summary.agent_page_url is None
    resolve_page.assert_not_called()

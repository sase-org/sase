"""Tests for provider-neutral ``parse_user_ref``."""

from __future__ import annotations

import pytest

from sase import workspace_provider
from sase.project_onboarding.refs import UserRefError, parse_user_ref
from sase.workspace_provider._hookspec import ParsedRepoRef, WorkflowMetadata

Stubs = tuple[
    dict[tuple[str, str], ParsedRepoRef],
    list[tuple[str, str]],
]


def _metadata(*workflow_types: str) -> list[WorkflowMetadata]:
    return [
        WorkflowMetadata(
            workflow_type=workflow_type,
            ref_pattern="",
            display_name=workflow_type,
            pre_allocated_env_prefix="",
        )
        for workflow_type in workflow_types
    ]


def _parsed(workflow_type: str, ref: str) -> ParsedRepoRef:
    return ParsedRepoRef(
        workflow_type=workflow_type,
        ref=ref,
        identity_key=f"{workflow_type}:{ref}",
        display=ref,
    )


@pytest.fixture
def provider_stubs(monkeypatch: pytest.MonkeyPatch) -> Stubs:
    """Stub the metadata and parse hooks behind ``parse_user_ref``."""

    calls: list[tuple[str, str]] = []
    table: dict[tuple[str, str], ParsedRepoRef] = {}

    monkeypatch.setattr(
        workspace_provider,
        "get_all_workflow_metadata",
        lambda: _metadata("gh", "git"),
    )

    def fake_parse(workflow_type: str, text: str) -> ParsedRepoRef | None:
        calls.append((workflow_type, text))
        return table.get((workflow_type, text))

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", fake_parse)
    return table, calls


class TestParseUserRef:
    def test_prefix_selects_provider(self, provider_stubs: Stubs) -> None:
        table, calls = provider_stubs
        table[("gh", "gh:sase-org/sase")] = _parsed("gh", "sase-org/sase")

        parsed = parse_user_ref("gh:sase-org/sase")

        assert parsed.workflow_type == "gh"
        assert parsed.ref == "sase-org/sase"
        assert [workflow for workflow, _ in calls] == ["gh"]

    def test_unprefixed_single_match_wins(self, provider_stubs: Stubs) -> None:
        table, _ = provider_stubs
        table[("git", "demo")] = _parsed("git", "demo")

        assert parse_user_ref("demo").workflow_type == "git"

    def test_unprefixed_multiple_matches_are_ambiguous(
        self, provider_stubs: Stubs
    ) -> None:
        table, _ = provider_stubs
        table[("gh", "demo")] = _parsed("gh", "demo")
        table[("git", "demo")] = _parsed("git", "demo")

        with pytest.raises(UserRefError, match="ambiguous"):
            parse_user_ref("demo")

    def test_unknown_text_is_not_recognized(self, provider_stubs: Stubs) -> None:
        del provider_stubs

        with pytest.raises(UserRefError, match="not recognized"):
            parse_user_ref("???no-such-ref???")

    def test_blank_text_is_not_recognized(self, provider_stubs: Stubs) -> None:
        del provider_stubs

        with pytest.raises(UserRefError, match="not recognized"):
            parse_user_ref("   ")

    def test_explicit_workflow_type_filters_providers(
        self, provider_stubs: Stubs
    ) -> None:
        table, calls = provider_stubs
        table[("git", "demo")] = _parsed("git", "demo")
        table[("gh", "demo")] = _parsed("gh", "demo")

        assert parse_user_ref("demo", workflow_type="git").workflow_type == "git"
        assert [workflow for workflow, _ in calls] == ["git"]

    def test_explicit_unknown_workflow_type_is_not_recognized(
        self, provider_stubs: Stubs
    ) -> None:
        del provider_stubs

        with pytest.raises(UserRefError, match="not recognized"):
            parse_user_ref("demo", workflow_type="gl")

    def test_error_is_a_value_error(self, provider_stubs: Stubs) -> None:
        del provider_stubs

        assert issubclass(UserRefError, ValueError)

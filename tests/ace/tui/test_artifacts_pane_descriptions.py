"""Description resolution for Artifacts pane contracts."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.ace.tui import _artifact_tab_descriptions as descriptions
from sase.ace.tui import _artifact_tab_discovery as discovery
from sase.ace.tui import artifact_tabs
from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui._artifact_tab_model import ProviderDiscoveryIssue, ProviderLoadResult


@pytest.fixture(autouse=True)
def _clear_description_cache() -> Iterator[None]:
    descriptions._configured_pane_descriptions_for_token.cache_clear()
    yield
    descriptions._configured_pane_descriptions_for_token.cache_clear()


def test_description_ladder_resolves_fields_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        {
            "ace": {
                "artifacts": {
                    "panes": {
                        "beads": {
                            "description": "Configured bead summary",
                        }
                    }
                }
            }
        },
        token=("config-summary",),
    )

    result = descriptions.resolve_pane_description(
        "beads",
        label="Bead",
        provider_summary="Provider bead summary",
        provider_body="",
    )

    assert result.summary == "Configured bead summary"
    assert result.summary_source == "config"
    assert result.body == descriptions.BUILTIN_PANE_DESCRIPTIONS["beads"][1]
    assert result.body_source == "builtin"


def test_provider_and_builtin_rungs_win_over_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, {}, token=("provider",))

    provider = descriptions.resolve_pane_description(
        "beads",
        label="Bead",
        provider_summary="Provider summary",
        provider_body="Provider body",
    )
    assert provider.summary == "Provider summary"
    assert provider.summary_source == "provider"
    assert provider.body == "Provider body"
    assert provider.body_source == "provider"

    builtin = descriptions.resolve_pane_description(
        "files",
        label="File",
        provider_summary="",
        provider_body="",
    )
    assert builtin.summary == descriptions.BUILTIN_PANE_DESCRIPTIONS["files"][0]
    assert builtin.summary_source == "builtin"
    assert builtin.body_source == "builtin"

    fallback = descriptions.resolve_pane_description(
        "ref:notes",
        label="Notes",
        provider_summary="",
        provider_body="",
    )
    assert (
        fallback.summary
        == "Notes documents contributed by this project's sidecar repos."
    )
    assert fallback.summary_source == "fallback"
    assert fallback.body == ""
    assert fallback.body_source == "fallback"


def test_description_sanitization() -> None:
    assert (
        descriptions.sanitize_description(
            "  First\tline\nsecond\x00 line  ", max_len=80
        )
        == "First line second line"
    )
    assert (
        descriptions.sanitize_description(
            "First\nline\n\nSecond\tparagraph\x07",
            max_len=80,
            preserve_paragraphs=True,
        )
        == "First line\n\nSecond paragraph"
    )
    assert descriptions.sanitize_description("x" * 12, max_len=8) == "xxxxxxx…"
    assert descriptions.sanitize_description(42, max_len=80) == ""


def test_non_string_config_value_falls_through_to_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        {
            "ace": {
                "artifacts": {
                    "panes": {"patches": {"description": 42}},
                }
            }
        },
        token=("non-string",),
    )

    result = descriptions.resolve_pane_description(
        "patches",
        label="Patch",
        provider_summary="",
        provider_body="",
    )

    assert result.summary == descriptions.BUILTIN_PANE_DESCRIPTIONS["patches"][0]
    assert result.summary_source == "builtin"


def test_every_resolved_descriptor_has_a_description_including_degraded_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, {}, token=("total",))
    monkeypatch.setattr(artifact_tabs, "provider_source_token", lambda: ("providers",))
    monkeypatch.setattr(
        artifact_tabs,
        "load_project_provider_records",
        lambda *, project: ProviderLoadResult(
            records=(),
            issues=(
                ProviderDiscoveryIssue(
                    message="provider missing",
                    code="missing_ref_provider",
                    kind="notes",
                    source="test",
                ),
            ),
        ),
    )
    artifact_tabs.reset_artifacts_subtabs_cache()

    try:
        descriptors = artifact_tabs.resolve_artifacts_subtabs()
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()

    assert all(descriptor.description for descriptor in descriptors)
    degraded = next(
        descriptor for descriptor in descriptors if descriptor.id == "ref:notes"
    )
    assert degraded.is_degraded
    assert degraded.resolved_contract.description_source == "fallback"


def test_ref_plan_config_override_resolves_with_colon_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        {
            "ace": {
                "artifacts": {
                    "panes": {
                        "ref:plan": {
                            "description": "Configured plan summary",
                            "description_body": "Configured plan body",
                        }
                    }
                }
            }
        },
        token=("ref-plan",),
    )

    contract = compile_provider_contract(
        kind="plan",
        label="Plan",
        icon="P",
        accent="#AF87FF",
        spec=None,
        provider_spec_digest="plan",
    ).contract

    assert contract.description == "Configured plan summary"
    assert contract.description_body == "Configured plan body"
    assert contract.description_source == "config"
    assert contract.description_body_source == "config"


def test_provider_source_token_changes_with_merged_config_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter((("config", 1), ("config", 2)))
    monkeypatch.setattr(discovery, "list_project_records", lambda *args, **kwargs: ())
    monkeypatch.setattr(discovery, "current_config_token", lambda: next(tokens))

    first = discovery.provider_source_token()
    second = discovery.provider_source_token()

    assert first is not None
    assert second is not None
    assert first != second


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, object],
    *,
    token: tuple[object, ...],
) -> None:
    descriptions._configured_pane_descriptions_for_token.cache_clear()
    monkeypatch.setattr(descriptions, "current_config_token", lambda: token)
    monkeypatch.setattr(descriptions, "load_merged_config", lambda: config)

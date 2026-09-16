"""Tests for the Ctrl+K prompt-history project-filter adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import sase.ace.patch.cache as patch_cache
import sase.history.prompt_history_project_filter as project_filter
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.core.prompt_history_filter_wire import PromptHistoryProjectIdentity
from sase.history.prompt_history_project_filter import (
    PromptHistoryProjectCatalog,
    build_prompt_history_seed_from_draft,
    filtered_prompt_history_row_indices,
    prepare_prompt_history_row_facts,
)


def _project_record(
    project_name: str,
    *,
    display_name: str | None = None,
    aliases: tuple[str, ...] = (),
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=3,
        project_name=project_name,
        project_dir=f"/tmp/{project_name}",
        project_file=f"/tmp/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=None,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=list(aliases),
        display_name=display_name,
    )


def _catalog(*entries: PromptHistoryProjectIdentity) -> PromptHistoryProjectCatalog:
    return PromptHistoryProjectCatalog(entries=tuple(entries))


def test_catalog_load_derives_provider_and_patch_raw_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        project_filter,
        "list_project_records",
        lambda *_args, **_kwargs: [
            _project_record(
                "gh_sase-org__sase", display_name="sase", aliases=("sase-main",)
            ),
            _project_record("home"),
        ],
    )
    monkeypatch.setattr(
        patch_cache,
        "find_all_patches_cached",
        lambda **_kwargs: [
            SimpleNamespace(project_name="gh_sase-org__sase", name="fix-parser"),
        ],
    )

    catalog = PromptHistoryProjectCatalog.load()
    by_key = {entry.key: entry for entry in catalog.entries}

    assert by_key["gh_sase-org__sase"].label == "sase"
    assert by_key["gh_sase-org__sase"].aliases == ["sase-main"]
    assert "sase-org/sase" in by_key["gh_sase-org__sase"].raw_refs
    assert "fix-parser" in by_key["gh_sase-org__sase"].raw_refs
    assert by_key["home"].raw_refs == []


def test_catalog_load_degrades_to_empty_on_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> list[ProjectRecordWire]:
        raise OSError("disk unavailable")

    monkeypatch.setattr(project_filter, "list_project_records", _boom)

    catalog = PromptHistoryProjectCatalog.load()

    assert catalog.entries == ()


@pytest.mark.parametrize(
    ("draft", "expected_seed_text", "expected_hint"),
    [
        ("#gh:sase fix parser", "project:sase fix parser", None),
        ("#git:sase fix parser", "project:sase fix parser", None),
        ("#gh:gh_sase-org__sase fix parser", "project:sase fix parser", None),
        ("#gh:sase-org/sase fix parser", "project:sase fix parser", None),
        ("#gh:sase", "project:sase ", None),
        (
            "%m:opus #gh:sase fix parser",
            "project:sase %m:opus fix parser",
            None,
        ),
        ("fix parser", "fix parser", None),
        ("", "", None),
        (
            "#gh:totally-unregistered-thing fix parser",
            "fix parser",
            "Project scope unavailable; searching all loaded prompts",
        ),
    ],
)
def test_build_prompt_history_seed_from_draft_examples(
    draft: str, expected_seed_text: str, expected_hint: str | None
) -> None:
    catalog = _catalog(
        PromptHistoryProjectIdentity(
            key="gh_sase-org__sase",
            label="sase",
            raw_refs=["sase-org/sase"],
        )
    )

    seed = build_prompt_history_seed_from_draft(draft, catalog)

    assert seed.seed_text == expected_seed_text
    assert seed.hint == expected_hint


def test_prepare_row_facts_resolves_each_multi_prompt_segment() -> None:
    catalog = _catalog(
        PromptHistoryProjectIdentity(key="sase"),
        PromptHistoryProjectIdentity(key="sase-core"),
    )
    text = "#gh:sase fix parser\n---\n#gh:sase-core fix build"

    facts = prepare_prompt_history_row_facts(0, text, text, catalog)

    assert facts.segment_project_keys == ["sase", "sase-core"]
    assert facts.segment_raw_refs == ["sase", "sase-core"]


def test_prepare_row_facts_legacy_record_has_no_inferred_project() -> None:
    catalog = _catalog(PromptHistoryProjectIdentity(key="sase"))

    facts = prepare_prompt_history_row_facts(
        0, "fix parser without any tag", "fix parser without any tag", catalog
    )

    assert facts.segment_project_keys == [None]
    assert facts.segment_raw_refs == [None]


def test_filtered_prompt_history_row_indices_matches_project_scope() -> None:
    catalog = _catalog(PromptHistoryProjectIdentity(key="sase"))
    compiled = catalog.compile_query("project:sase fix")
    matching = prepare_prompt_history_row_facts(
        0, "#gh:sase fix parser", "#gh:sase fix parser", catalog
    )
    other = prepare_prompt_history_row_facts(
        1, "#gh:other fix parser", "#gh:other fix parser", catalog
    )

    assert filtered_prompt_history_row_indices(
        compiled, [matching, other]
    ) == frozenset({0})

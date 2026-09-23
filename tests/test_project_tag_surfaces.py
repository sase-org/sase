"""Tests for tag-surfaces accent styling (sase-16n.7).

Covers the shared helpers and the CLI/project render additions: project
columns use the catalog accent with a fail-open fallback, preview bodies
overlay only ``+tag`` substrings, the ACE query ``+project`` shorthand
shares the tag accent, and ``sase project list/show`` expose TAG data.
"""

from __future__ import annotations

import pytest
from rich.text import Text

import sase.project_tags.catalog as tag_catalog_module
from sase.ace.query.highlighting import (
    QUERY_TOKEN_STYLES,
    style_for_query_token,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_accents import PROJECT_ACCENTS
from sase.project_tag_style import (
    accent_for_project_ref,
    project_column_style,
    rich_text_with_project_tags,
)
from sase.project_tags import ProjectTagCatalog, build_targets
from sase.project_tags.catalog import _clear_project_tag_catalog_cache


def _record(
    project_name: str,
    *,
    state: str = "enabled",
    display_name: str | None = None,
    vcs_kind: str | None = "gh",
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state=state,
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
        is_project=True,
        vcs_kind=vcs_kind,
    )


def _catalog() -> ProjectTagCatalog:
    records = [_record("sase"), _record("bob-cli")]
    targets = tuple(
        build_targets(
            records,
            detect_workflow_type=lambda _pf: "gh",
            get_display_name=lambda wf: "GitHub" if wf == "gh" else wf,
        )
    )
    return ProjectTagCatalog(
        targets=targets,
        accent_palette=tuple(PROJECT_ACCENTS),
        signature=("test",),
    )


@pytest.fixture()
def warm_catalog():
    catalog = _catalog()
    tag_catalog_module._CATALOG_CACHE = (catalog.signature, catalog)  # noqa: SLF001
    yield catalog
    _clear_project_tag_catalog_cache()


def _accent_for_key(catalog: ProjectTagCatalog, key: str) -> str:
    for target in catalog.targets:
        if target.key == key:
            assert target.accent is not None
            return target.accent
    raise AssertionError(f"missing target {key}")


def test_accent_lookup_matches_key_case_insensitively(warm_catalog) -> None:
    accent = accent_for_project_ref("SASE")
    assert accent == _accent_for_key(warm_catalog, "sase")
    assert accent is not None


def test_accent_lookup_unknown_returns_none(warm_catalog) -> None:
    assert accent_for_project_ref("no-such-project-xyz") is None


def test_accent_lookup_cold_catalog_returns_none() -> None:
    _clear_project_tag_catalog_cache()
    assert accent_for_project_ref("sase") is None


def test_project_column_style_falls_back() -> None:
    _clear_project_tag_catalog_cache()
    assert project_column_style("sase", fallback="cyan") == "cyan"


def test_project_column_style_uses_accent(warm_catalog) -> None:
    expected = _accent_for_key(warm_catalog, "sase")
    assert project_column_style("sase", fallback="cyan") == expected


def test_rich_text_without_plus_has_no_spans() -> None:
    text = rich_text_with_project_tags("plain prompt, no tags")
    assert isinstance(text, Text)
    assert text.plain == "plain prompt, no tags"
    assert text.spans == []


def test_rich_text_with_unknown_tag_leaves_warning_span(warm_catalog) -> None:
    text = rich_text_with_project_tags("+nosuchproject-xyz did things")
    assert text.plain == "+nosuchproject-xyz did things"
    # Unknown anchored tags get the warning style; unanchored unknown text
    # stays unstyled. Either way the helper never raises and keeps text.
    assert isinstance(text.spans, list)


def test_query_shorthand_uses_project_accent(warm_catalog) -> None:
    accent = _accent_for_key(warm_catalog, "sase")
    assert style_for_query_token("+sase", "shorthand") == f"bold {accent}"


def test_query_shorthand_unknown_keeps_default(warm_catalog) -> None:
    assert (
        style_for_query_token("+nosuchproject-xyz", "shorthand")
        == QUERY_TOKEN_STYLES["shorthand"]
    )


def test_query_non_project_shorthand_keeps_default(warm_catalog) -> None:
    assert style_for_query_token("%m", "shorthand") == QUERY_TOKEN_STYLES["shorthand"]


def test_project_json_includes_tag_fields() -> None:
    from sase.main.project_handler_render import record_to_json_dict

    record = _record("sase")
    payload = record_to_json_dict(record, among=("sase",))
    assert payload["tag"] == "+sase"
    assert payload["workflow_type"] == "gh"
    assert isinstance(payload["accent"], str)


def test_project_json_untaggable_name_has_null_tag() -> None:
    from sase.main.project_handler_render import record_to_json_dict

    record = _record("9lives", vcs_kind="git")
    payload = record_to_json_dict(record, among=("9lives",))
    assert payload["tag"] is None


def test_project_list_table_has_tag_column(capsys) -> None:
    from sase.main.project_handler_render import print_records_table

    print_records_table([_record("sase"), _record("bob-cli")], "enabled")
    out = capsys.readouterr().out
    assert "TAG" in out
    assert "+sase" in out


def test_project_show_prints_tag(capsys) -> None:
    from sase.main.project_handler_render import print_record_detail

    print_record_detail(_record("sase"), among=("sase",))
    out = capsys.readouterr().out
    assert "Tag: +sase" in out


def test_pager_xprompt_body_stays_plain_for_syntax_highlighting(
    warm_catalog,
) -> None:
    from sase.ace.tui.actions.agents._metadata_pager_conversation import (
        _tag_styled_xprompt_body,
    )

    # Tag-form input (humanize tagify of ``#`` refs is covered by the
    # humanizer tests with a populated display snapshot; pytest isolates
    # SASE_HOME so the snapshot is empty here).
    body = _tag_styled_xprompt_body("+sase do things")
    assert isinstance(body, Text)
    assert body.plain == "+sase do things"
    # Tag accents arrive through the pager highlighter's PROJECT_TAG spans,
    # never as producer styling: producer spans force a PRESERVED pass that
    # drops all Markdown highlighting.
    assert body.spans == []


def test_pager_markdown_highlights_tags_and_markdown_together(
    warm_catalog,
) -> None:
    from sase.pager.syntax import (
        SyntaxDisposition,
        SyntaxRole,
        highlight_source,
    )

    source = "# Title\n\n+sase do things\n"
    result = highlight_source(source, "markdown", base_text=Text(source))

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    roles = {span.role for span in result.spans}
    assert SyntaxRole.MARKDOWN_HEADING in roles
    assert SyntaxRole.PROJECT_TAG in roles
    tag_spans = [span for span in result.spans if span.role is SyntaxRole.PROJECT_TAG]
    assert len(tag_spans) == 2
    assert source[tag_spans[0].start : tag_spans[0].end] == "+"
    assert source[tag_spans[1].start : tag_spans[1].end] == "sase"
    accent = next(
        target.accent for target in warm_catalog.targets if target.key == "sase"
    )
    assert accent is not None
    assert tag_spans[0].style == f"dim {accent}"
    assert tag_spans[1].style == f"bold {accent}"


def test_pager_ignores_unknown_tags(warm_catalog) -> None:
    from sase.pager.syntax import SyntaxRole, highlight_source

    source = "fix +no-such-project-xyz now\n"
    result = highlight_source(source, "markdown", base_text=Text(source))

    assert all(span.role is not SyntaxRole.PROJECT_TAG for span in result.spans)


def test_pager_never_styles_tags_inside_fences(warm_catalog) -> None:
    from sase.pager.syntax import SyntaxRole, highlight_source

    source = "# Title\n\n```md\n+sase in fence\n```\n\n+sase in prose\n"
    result = highlight_source(source, "markdown", base_text=Text(source))

    tag_texts = [
        source[span.start : span.end]
        for span in result.spans
        if span.role is SyntaxRole.PROJECT_TAG
    ]
    assert "".join(tag_texts) == "+sase"
    assert source.index("+sase in prose") < result.spans[-1].end


def test_pager_home_tag_uses_neutral_style(warm_catalog) -> None:
    import sase.project_tags.catalog as tag_catalog_module
    from sase.core.project_lifecycle_wire import PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION
    from sase.core.project_lifecycle_wire import ProjectRecordWire
    from sase.pager.syntax import SyntaxRole, highlight_source
    from sase.project_tags import ProjectTagCatalog, build_targets

    targets = tuple(
        build_targets(
            [
                ProjectRecordWire(
                    schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
                    project_name="home",
                    project_dir="/tmp/projects/home",
                    project_file="/tmp/projects/home/home.sase",
                    archive_file=None,
                    workspace_dir="/tmp/workspaces/home",
                    state="enabled",
                    state_explicit=False,
                    system_managed=False,
                    active_claim_count=0,
                    launchable=True,
                    aliases=[],
                    warnings=[],
                    parse_warnings=[],
                    display_name=None,
                    is_project=True,
                    vcs_kind="gh",
                )
            ],
            detect_workflow_type=lambda _pf: "gh",
            get_display_name=lambda wf: "GitHub" if wf == "gh" else wf,
        )
    )
    catalog = ProjectTagCatalog(targets=targets, accent_palette=(), signature=("home",))
    tag_catalog_module._CATALOG_CACHE = (catalog.signature, catalog)  # noqa: SLF001
    try:
        source = "+home do things\n"
        result = highlight_source(source, "markdown", base_text=Text(source))
    finally:
        from sase.project_tags.catalog import _clear_project_tag_catalog_cache

        _clear_project_tag_catalog_cache()

    tag_spans = [span for span in result.spans if span.role is SyntaxRole.PROJECT_TAG]
    # Neutral sigil and name share the same ``dim`` style, so the budget
    # merges them into one span covering the whole tag.
    assert len(tag_spans) == 1
    assert source[tag_spans[0].start : tag_spans[0].end] == "+home"
    assert tag_spans[0].style == "dim"


def test_launch_preview_styles_tags(warm_catalog) -> None:
    from sase.ace.tui.modals.launch_approval_modal import _tag_styled_preview

    rendered = _tag_styled_preview("+sase do things")
    plain = rendered.plain if isinstance(rendered, Text) else str(rendered)
    assert "+sase" in plain

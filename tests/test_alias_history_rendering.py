"""Tests for the pure alias-history rendering helpers."""

from __future__ import annotations

from sase.ace.tui.modals.alias_history_rendering import (
    alias_history_detail_text,
    alias_history_empty_text,
    alias_history_footer_markup,
    alias_history_group_header_text,
    alias_history_row_text,
    alias_history_title_text,
    build_alias_history_rows,
)
from sase.core.agent_scan_wire_markers import UsedXPromptWire
from sase.llm_provider.alias_history import AliasHistoryProvenance

from ._alias_history_helpers import make_entry as _entry
from ._alias_history_helpers import make_group as _group
from ._alias_history_helpers import make_run as _run
from ._alias_history_helpers import make_view as _view

_NOW = 2_000_000_000.0


# -- title ------------------------------------------------------------------


def test_title_includes_badge_for_single_alias_entry() -> None:
    entry = _entry(
        effective_provider="claude", effective_model="opus", effective_effort="high"
    )
    text = alias_history_title_text(entry, None)
    assert "@large" in text.plain
    assert "opus" in text.plain


def test_title_omits_badge_for_bucket_entry() -> None:
    entry = _entry(aliases=("a", "b"), title_label="research")
    text = alias_history_title_text(entry, None)
    assert "research" in text.plain
    assert "opus" not in text.plain


def test_title_shows_ownership_accent_marker_for_user_owned() -> None:
    entry = _entry(is_user_owned=True)
    text = alias_history_title_text(entry, None)
    assert "▌" in text.plain


def test_title_reports_recorded_returned_and_status_counts() -> None:
    entry = _entry()
    view = _view(
        [_group("large", [_run(), _run(rollup_status="failed", status="failed")])]
    )
    text = alias_history_title_text(entry, view)
    assert "2 recorded" in text.plain
    assert "2 shown" in text.plain
    assert "✓1" in text.plain
    assert "✗1" in text.plain


# -- rows ---------------------------------------------------------------


def test_row_shows_status_glyph_for_each_rollup_status() -> None:
    done = alias_history_row_text(_run(rollup_status="done"), now=_NOW)
    failed = alias_history_row_text(
        _run(rollup_status="failed", status="failed"), now=_NOW
    )
    running = alias_history_row_text(
        _run(rollup_status="running", status="running"), now=_NOW
    )
    assert done.plain.startswith("✓")
    assert failed.plain.startswith("✗")
    assert running.plain.startswith("▶")


def test_row_shows_hidden_and_retry_markers() -> None:
    text = alias_history_row_text(_run(hidden=True, retry_attempt=2), now=_NOW)
    assert "◌" in text.plain
    assert "↻2" in text.plain


def test_row_shows_provenance_chip_for_each_kind() -> None:
    for kind, label in (
        ("direct", "direct"),
        ("default", "default"),
        ("indirect", "via @coder"),
        ("unrecorded", "unrecorded"),
    ):
        run = _run(
            provenance=AliasHistoryProvenance(kind=kind, label=label, via_alias="coder")
        )
        text = alias_history_row_text(run, now=_NOW)
        assert label in text.plain


def test_row_includes_agent_identity_and_project() -> None:
    text = alias_history_row_text(
        _run(agent_name="my_agent", project_name="sase"), now=_NOW
    )
    assert "my_agent" in text.plain
    assert "sase" in text.plain


# -- group headers / bucket row assembly ---------------------------------


def test_group_header_reports_alias_and_counts() -> None:
    group = _group("research_a", [_run(), _run()])
    text = alias_history_group_header_text(group)
    assert "@research_a" in text.plain
    assert "2 recorded" in text.plain


def test_build_rows_single_alias_has_no_group_header_or_spacer() -> None:
    entry = _entry(aliases=("large",))
    view = _view([_group("large", [_run()])])
    specs = build_alias_history_rows(view, entry=entry, now=_NOW)
    ids = [spec.option_id for spec in specs]
    assert not any(option_id.startswith("__group__") for option_id in ids)
    assert not any(option_id.startswith("__spacer__") for option_id in ids)
    assert ids == ["large:/tmp/a"]


def test_build_rows_bucket_has_one_spacer_between_groups_no_leading_trailing() -> None:
    entry = _entry(aliases=("a", "b"), title_label="research")
    view = _view(
        [
            _group("a", [_run(artifact_dir="/tmp/a1")]),
            _group("b", [_run(artifact_dir="/tmp/b1")]),
        ]
    )
    specs = build_alias_history_rows(view, entry=entry, now=_NOW)
    ids = [spec.option_id for spec in specs]
    assert ids[0] == "__group__:a"
    assert ids.count("__spacer__:b") == 1
    assert ids[-1] == "b:/tmp/b1"
    assert not ids[0].startswith("__spacer__")
    assert not ids[-1].startswith("__spacer__")


def test_build_rows_group_headers_and_spacers_are_disabled() -> None:
    entry = _entry(aliases=("a", "b"), title_label="research")
    view = _view([_group("a", [_run()]), _group("b", [_run()])])
    specs = build_alias_history_rows(view, entry=entry, now=_NOW)
    disabled_ids = {spec.option_id for spec in specs if spec.disabled}
    assert "__group__:a" in disabled_ids
    assert "__group__:b" in disabled_ids
    assert "__spacer__:b" in disabled_ids


def test_build_rows_empty_group_renders_disabled_hint() -> None:
    entry = _entry(aliases=("a", "b"), title_label="research")
    view = _view([_group("a", []), _group("b", [_run()])])
    specs = build_alias_history_rows(view, entry=entry, now=_NOW)
    empty = next(spec for spec in specs if spec.option_id == "__empty__:a")
    assert empty.disabled is True
    assert "@a" in empty.text.plain


def test_build_rows_preserves_adapter_order() -> None:
    entry = _entry(aliases=("large",))
    runs = [_run(artifact_dir="/tmp/newest"), _run(artifact_dir="/tmp/oldest")]
    view = _view([_group("large", runs)])
    specs = build_alias_history_rows(view, entry=entry, now=_NOW)
    assert [spec.option_id for spec in specs] == [
        "large:/tmp/newest",
        "large:/tmp/oldest",
    ]


# -- detail strip ---------------------------------------------------------


def test_detail_trail_resolves_to_concrete_provider_model() -> None:
    run = _run(model_alias_trail=("coder", "large"))
    text = alias_history_detail_text(run, entry=_entry())
    assert "@coder" in text.plain
    assert "@large" in text.plain
    assert "opus" in text.plain


def test_detail_origin_line_for_each_provenance_kind() -> None:
    cases = {
        "direct": "explicit %model directive",
        "default": "configured default model",
        "unrecorded": "unrecorded — no alias origin was captured",
    }
    for kind, expected in cases.items():
        run = _run(provenance=AliasHistoryProvenance(kind=kind, label=kind))
        text = alias_history_detail_text(run, entry=_entry())
        assert expected in text.plain

    indirect_run = _run(
        provenance=AliasHistoryProvenance(
            kind="indirect", label="via @coder", via_alias="coder"
        )
    )
    text = alias_history_detail_text(indirect_run, entry=_entry())
    assert "via @coder" in text.plain


def test_detail_only_renders_present_fields() -> None:
    run = _run(
        workspace_num=None, bead_id=None, cl_name=None, retry_attempt=None, hidden=False
    )
    text = alias_history_detail_text(run, entry=_entry())
    assert "Workspace:" not in text.plain
    assert "Bead:" not in text.plain
    assert "Patch:" not in text.plain
    assert "Retry:" not in text.plain
    assert "Hidden:" not in text.plain


def test_detail_renders_available_fields() -> None:
    run = _run(
        workspace_num=3,
        bead_id="sase-1.2",
        cl_name="my-patch",
        retry_attempt=2,
        hidden=True,
    )
    text = alias_history_detail_text(run, entry=_entry())
    assert "Workspace: #3" in text.plain
    assert "Bead: sase-1.2" in text.plain
    assert "Patch: my-patch" in text.plain
    assert "Retry: attempt #2" in text.plain
    assert "Hidden: yes" in text.plain


def test_detail_renders_prompt_snippet_when_present() -> None:
    run = _run(prompt_snippet="Implement the alias history panel.")
    text = alias_history_detail_text(run, entry=_entry())
    assert "Implement the alias history panel." in text.plain


def test_detail_renders_xprompt_context() -> None:
    run = _run(used_xprompts=(UsedXPromptWire(name="research", kind="workflow"),))
    text = alias_history_detail_text(run, entry=_entry())
    assert "#research" in text.plain


def test_detail_falls_back_to_empty_text_when_no_run() -> None:
    entry = _entry(aliases=("large",))
    text = alias_history_detail_text(None, entry=entry)
    assert "@large" in text.plain


# -- empty state ------------------------------------------------------------


def test_empty_text_names_every_requested_alias() -> None:
    entry = _entry(aliases=("a", "b"), title_label="research")
    text = alias_history_empty_text(entry)
    assert "@a" in text.plain
    assert "@b" in text.plain


# -- footer -----------------------------------------------------------------


def test_footer_reflects_hidden_state() -> None:
    shown = alias_history_footer_markup(include_hidden=True, has_more=False)
    excluded = alias_history_footer_markup(include_hidden=False, has_more=False)
    assert "showing" in shown
    assert "excluded" in excluded


def test_footer_reflects_more_available() -> None:
    with_more = alias_history_footer_markup(include_hidden=False, has_more=True)
    without_more = alias_history_footer_markup(include_hidden=False, has_more=False)
    assert "more available" in with_more
    assert "more available" not in without_more

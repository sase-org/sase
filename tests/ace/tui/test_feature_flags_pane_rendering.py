"""Pure render coverage for the Config Flags pane."""

from __future__ import annotations

import io
import time
from datetime import date

from rich.console import Console

from sase.ace.tui.modals.feature_flags_pane_rendering import (
    ROLLOUT_FLAG_KEY,
    ROLLOUT_RECOVERY_COMMAND,
    build_detail_meta,
    build_detail_title,
    build_empty_catalog_message,
    build_error_message,
    build_flag_row_text,
    build_no_match_message,
    build_panel_footer,
    build_panel_header,
    build_toggle_confirmation,
    filter_flag_views,
)
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDiagnostic,
    FlagKind,
    FlagSource,
)
from tests.feature_flags._helpers import demo_flag, flag_bead

_TODAY = date(2026, 8, 21)
_RELEASE = "0.16.0"


def _view(
    key: str,
    *,
    kind: FlagKind = "beta",
    enabled: bool = False,
    source: FlagSource = "default",
    source_detail: str = "",
    saved: bool | None = None,
    due_state: str | None = None,
    bead: bool = True,
    description: str | None = None,
) -> FlagView:
    definition = demo_flag(key, kind=kind, description=description)
    return FlagView(
        definition=definition,
        decision=FeatureFlagDecision(
            key=key,
            enabled=enabled,
            default=definition.default,
            source=source,
            source_detail=source_detail,
            overridden=source != "default",
        ),
        bead=flag_bead(key, bead_id=f"sase-{key[:2]}") if bead else None,
        due_state=due_state,  # type: ignore[arg-type]
        saved=saved,
    )


def test_header_counts_registered_on_and_saved() -> None:
    header = build_panel_header(
        (
            _view("alpha", enabled=True, saved=True),
            _view("beta_flag", enabled=False),
            _view("gamma", kind="sunset", enabled=True, saved=False),
        )
    )
    assert "FLAGS" in header.plain
    assert "3 registered" in header.plain
    assert "2 on" in header.plain
    assert "2 saved" in header.plain


def test_header_loading_and_error_states() -> None:
    assert "loading" in build_panel_header((), loading=True).plain.casefold()
    assert "error" in build_panel_header((), error="boom").plain.casefold()


def test_rows_encode_kind_effective_state_and_urgency() -> None:
    on_beta = build_flag_row_text(_view("artifact_links", enabled=True))
    off_beta = build_flag_row_text(_view("cleanup_gate", enabled=False))
    sunset = build_flag_row_text(_view("prettier_enabled", kind="sunset", enabled=True))
    shadowed = build_flag_row_text(
        _view("shadowed", enabled=True, source="cli", saved=False)
    )
    due = build_flag_row_text(_view("overdue", enabled=False, due_state="due"))
    soon = build_flag_row_text(_view("aging", enabled=True, due_state="soon"))

    assert "ON" in on_beta.plain and "β" in on_beta.plain
    assert "OFF" in off_beta.plain
    assert "↗" in sunset.plain
    assert "!" in shadowed.plain
    assert "due" in due.plain
    assert "soon" in soon.plain


def test_filter_matches_key_description_kind_state_and_provenance() -> None:
    views = (
        _view(
            "artifact_links",
            enabled=True,
            source="state",
            saved=True,
            description="typed artifact links",
        ),
        _view("cleanup_gate", kind="sunset", enabled=False, source="cli"),
    )
    assert [str(v.definition.key) for v in filter_flag_views(views, "artifact")] == [
        "artifact_links"
    ]
    assert [str(v.definition.key) for v in filter_flag_views(views, "typed")] == [
        "artifact_links"
    ]
    assert [str(v.definition.key) for v in filter_flag_views(views, "sunset")] == [
        "cleanup_gate"
    ]
    assert [str(v.definition.key) for v in filter_flag_views(views, "off")] == [
        "cleanup_gate"
    ]
    assert [str(v.definition.key) for v in filter_flag_views(views, "saved")] == [
        "artifact_links"
    ]
    assert [str(v.definition.key) for v in filter_flag_views(views, "cli")] == [
        "cleanup_gate"
    ]


def test_detail_card_separates_effective_saved_and_bead_metadata() -> None:
    view = _view(
        "artifact_links",
        enabled=True,
        source="state",
        source_detail="/tmp/feature_flags.json",
        saved=True,
        due_state="live",
    )
    title = build_detail_title(view)
    meta = build_detail_meta(
        view,
        state_path="/tmp/feature_flags.json",
        today=_TODAY,
        release=_RELEASE,
    )
    title_plain = title.plain
    buf = io.StringIO()
    Console(file=buf, color_system=None, highlight=False, width=160).print(meta)
    joined = buf.getvalue().upper()
    assert "artifact_links" in title_plain
    assert "ON" in title_plain
    assert "BETA" in title_plain
    assert "EFFECTIVE" in joined
    assert "SAVED" in joined
    assert "BEAD" in joined
    assert "REMOVE BY" in joined


def test_empty_error_and_no_match_cards_are_intentional() -> None:
    assert "No feature flags are registered" in build_empty_catalog_message().plain
    assert "No flags match" in build_no_match_message("zzz").plain
    assert "zzz" in build_no_match_message("zzz").plain
    assert "Could not load" in build_error_message("boom").plain
    assert "boom" in build_error_message("boom").plain


def test_footer_changes_for_filter_and_mutation() -> None:
    idle = build_panel_footer(
        filter_open=False, has_selection=True, mutating=False
    ).plain
    filtering = build_panel_footer(
        filter_open=True, has_selection=True, mutating=False
    ).plain
    saving = build_panel_footer(
        filter_open=False, has_selection=True, mutating=True
    ).plain
    assert "filter" in idle
    assert "toggle" in idle
    assert "ACE + AXE" in idle
    assert "close filter" in filtering
    assert "saving" in saving


def test_confirmation_copy_is_cancel_first_and_warns_on_shadowing() -> None:
    view = _view(
        "artifact_links",
        enabled=False,
        source="cli",
        source_detail="--enable-feature",
        saved=True,
    )
    copy = build_toggle_confirmation(view, state_path="/tmp/feature_flags.json")
    assert copy.message == "ACE and AXE restart after active procs finish."
    assert "OFF -> ON" in copy.subject
    assert "/tmp/feature_flags.json" in copy.subject
    assert "Forced for this process" in copy.subject
    assert "--enable-feature" in copy.subject


def test_self_disable_confirmation_includes_cli_recovery() -> None:
    view = _view(
        ROLLOUT_FLAG_KEY,
        kind="sunset",
        enabled=True,
        source="default",
        description="The Config catalog exposes the Flags pane.",
    )
    copy = build_toggle_confirmation(view, state_path="/tmp/feature_flags.json")
    assert "ON -> OFF" in copy.subject
    assert "Flags pane will disappear" in copy.subject
    assert ROLLOUT_RECOVERY_COMMAND in copy.subject


def test_row_render_stays_under_key_to_paint_budget() -> None:
    view = _view("artifact_links", enabled=True, source="state", saved=True)
    samples = []
    for _ in range(200):
        started = time.perf_counter()
        build_flag_row_text(view)
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p95 = samples[int(0.95 * len(samples))]
    assert p95 < 16


def test_corrupt_diagnostics_render_on_the_card() -> None:
    view = _view("artifact_links", enabled=True)
    meta = build_detail_meta(
        view,
        state_path="/tmp/feature_flags.json",
        diagnostics=(
            FeatureFlagDiagnostic(
                severity="error",
                code="invalid_json",
                message="feature_flags.json is not valid JSON",
                source="/tmp/feature_flags.json",
            ),
        ),
        today=_TODAY,
        release=_RELEASE,
    )
    buf = io.StringIO()
    Console(file=buf, color_system=None, highlight=False, width=160).print(meta)
    assert "not valid JSON" in buf.getvalue()

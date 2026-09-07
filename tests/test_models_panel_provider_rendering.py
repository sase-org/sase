"""Models-panel provider-routing rendering tests."""

from __future__ import annotations

from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.ace.tui.modals.models_panel_duration import (
    KeepCurrentWindow,
    OverrideUntilCleared,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_provider_rendering import (
    duration_suffix,
    provider_description_text,
    provider_duration_modal,
    provider_priority_duration_modal,
    provider_summary_text,
    provider_title_line,
    render_provider_row,
)
from sase.ace.tui.modals.models_panel_provider_state import (
    disabled_explicit_provider_message,
    soft_explicit_provider_note,
)
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_MODE_SOFT
from sase.llm_provider.load_balancing import MemberAvailability
from tests._models_panel_provider_routing_helpers import disable, priority, status


def test_provider_disable_provenance_labels_known_and_unknown_sources() -> None:
    assert (
        provider_disable_provenance_label(disable("claude", source="ace")) == "manual"
    )
    assert (
        provider_disable_provenance_label(disable("claude", source="usage_limit"))
        == "usage-limit automatic"
    )
    assert (
        provider_disable_provenance_label(disable("claude", source="external_plugin"))
        == "external plugin"
    )


def test_render_provider_rows_show_all_states() -> None:
    available = render_provider_row(
        status("codex", model_count=3),
        colors={"codex": "#10A37F"},
        now=100.0,
    )
    missing = render_provider_row(
        status("grok", model_count=1, cli_available=False),
        colors={},
        now=100.0,
    )
    disabled = render_provider_row(
        status(
            "claude",
            active_disable=disable("claude", expires_at=3_820.0, source="usage_limit"),
        ),
        colors={"claude": "#D97757"},
        now=100.0,
    )

    assert available.plain == "CODEX          3 models     available"
    assert missing.plain == "GROK           1 model      CLI missing"
    assert (
        disabled.plain
        == "CLAUDE         2 models     disabled · usage-limit automatic · 1h2m left"
    )


def test_render_provider_row_shows_soft_state() -> None:
    row = render_provider_row(
        status(
            "claude",
            active_disable=disable(
                "claude",
                expires_at=3_820.0,
                source="ace",
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
        ),
        colors={"claude": "#D97757"},
        now=100.0,
    )

    assert row.plain == "CLAUDE         2 models     soft · manual · 1h2m left"


def test_render_provider_rows_show_priority_and_backup_states() -> None:
    record = priority("codex", expires_at=3_820.0)
    preferred = render_provider_row(
        status(
            "codex",
            priority=record,
            provenance=("priority",),
        ),
        colors={"codex": "#10A37F"},
        now=100.0,
    )
    backup = render_provider_row(
        status(
            "claude",
            availability=MemberAvailability.SPARING,
            priority=record,
            provenance=("priority_backup",),
        ),
        colors={"claude": "#D97757"},
        now=100.0,
    )

    assert preferred.plain == "CODEX          2 models     ★ priority · 1h2m left"
    assert backup.plain == "CLAUDE         2 models     backup · CODEX priority"


def test_render_provider_row_shows_unavailable_priority_intent() -> None:
    record = priority("codex", expires_at=3_820.0)
    row = render_provider_row(
        status(
            "codex",
            cli_available=False,
            availability=MemberAvailability.UNAVAILABLE,
            priority=record,
            provenance=("cli_missing", "priority"),
        ),
        colors={"codex": "#10A37F"},
        now=100.0,
    )

    assert row.plain == (
        "CODEX          2 models     CLI missing · ★ priority unavailable"
    )


def test_provider_description_lists_disabled_effect_and_aliases() -> None:
    description = provider_description_text(
        status(
            "claude",
            active_disable=disable("claude", expires_at=None, source="ace"),
            affected_aliases=("large", "medium", "xlarge"),
        ),
        now=100.0,
    )

    assert "New launches and fallbacks route around CLAUDE" in description.plain
    assert "running provider processes continue" in description.plain
    assert "manual disable until cleared." in description.plain
    assert "Affected aliases: @large, @medium, @xlarge." in description.plain


def test_provider_description_shows_unknown_disable_provenance() -> None:
    description = provider_description_text(
        status(
            "claude",
            active_disable=disable(
                "claude", expires_at=3_820.0, source="external_plugin"
            ),
        ),
        now=100.0,
    )

    assert "external plugin disable until" in description.plain


def test_provider_description_lists_soft_rules() -> None:
    description = provider_description_text(
        status(
            "claude",
            active_disable=disable(
                "claude",
                expires_at=None,
                source="ace",
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
            affected_aliases=("large", "medium"),
        ),
        now=100.0,
    )

    assert "Pools spare CLAUDE while another member can cover" in description.plain
    assert "|| fallbacks and explicit %model still use it" in description.plain
    assert "Running processes continue" in description.plain
    assert "manual soft disable until cleared" in description.plain
    assert "Affected aliases: @large, @medium." in description.plain


def test_provider_description_distinguishes_priority_backup() -> None:
    record = priority("codex", expires_at=3_820.0)
    description = provider_description_text(
        status(
            "claude",
            availability=MemberAvailability.SPARING,
            priority=record,
            provenance=("priority_backup",),
        ),
        now=100.0,
        priority=record,
    )

    assert "Enabled; CODEX has priority. Press c to clear priority." in (
        description.plain
    )
    assert "this provider remains usable" in description.plain


def test_provider_summary_text_mentions_active_priority() -> None:
    record = priority("codex", expires_at=3_820.0)
    text = provider_summary_text(
        (
            status("codex", priority=record, provenance=("priority",)),
            status(
                "claude",
                availability=MemberAvailability.SPARING,
                priority=record,
                provenance=("priority_backup",),
            ),
        ),
        priority=record,
        now=100.0,
    )

    assert "★ CODEX priority · 1h2m left" in text.plain
    assert "other providers remain backups" in text.plain


def test_provider_summary_text_marks_orphaned_priority_unavailable() -> None:
    record = priority("codex", expires_at=3_820.0)
    text = provider_summary_text((), priority=record, now=100.0)

    assert "★ CODEX priority unavailable · 1h2m left" in text.plain
    assert "other providers remain backups" in text.plain


def test_provider_title_line_marks_soft_entries() -> None:
    text = provider_title_line(
        {
            "claude": disable(
                "claude",
                expires_at=None,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
            "codex": disable("codex", expires_at=3_820.0),
        },
        now=100.0,
    )

    assert text is not None
    assert text.plain == "disabled providers: CLAUDE soft until cleared · CODEX 1h2m"


def test_provider_title_line_marks_priority_entries() -> None:
    record = priority("codex", expires_at=3_820.0)
    text = provider_title_line(
        {
            "claude": disable(
                "claude",
                expires_at=None,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
        },
        now=100.0,
        priority=record,
    )

    assert text is not None
    assert text.plain == (
        "priority: CODEX ★ 1h2m · disabled providers: CLAUDE soft until cleared"
    )


def test_provider_duration_modal_titles_follow_mode() -> None:
    hard = provider_duration_modal("claude")
    soft = provider_duration_modal("claude", mode=PROVIDER_DISABLE_MODE_SOFT)
    keep = provider_duration_modal(
        "claude",
        mode=PROVIDER_DISABLE_MODE_SOFT,
        keep_current=KeepCurrentWindow(expires_at=None),
    )

    assert hard._title == "Disable CLAUDE"
    assert soft._title == "Soft-disable CLAUDE"
    assert keep._choices[0].key == "x"
    assert "until cleared" in keep._choices[0].title


def test_provider_priority_duration_modal_titles_follow_state() -> None:
    active = priority("codex", expires_at=3_820.0)
    same = provider_priority_duration_modal("codex", current_priority=active, now=100.0)
    replacing = provider_priority_duration_modal(
        "claude",
        current_priority=active,
        now=100.0,
    )

    assert same._title == "Change CODEX priority"
    assert replacing._title == "Prioritize CLAUDE"
    assert "Replaces CODEX priority" in replacing._choices[0].subtitle


def test_duration_suffix_keep_current_window() -> None:
    assert duration_suffix(KeepCurrentWindow(expires_at=1_000.0)) == (
        "with its current window"
    )
    assert duration_suffix(OverrideUntilCleared()) == "until cleared"
    assert duration_suffix(RelativeOverrideDuration(120.0)) == "for 2m"


def test_disabled_explicit_provider_message_is_hard_only() -> None:
    hard = {"claude": disable("claude", expires_at=None)}
    soft = {
        "claude": disable(
            "claude",
            expires_at=None,
            mode=PROVIDER_DISABLE_MODE_SOFT,
        )
    }

    assert (
        disabled_explicit_provider_message("claude/opus", hard, now=100.0) is not None
    )
    assert disabled_explicit_provider_message("claude/opus", soft, now=100.0) is None
    assert soft_explicit_provider_note("claude/opus", hard, now=100.0) is None
    note = soft_explicit_provider_note("claude/opus", soft, now=100.0)
    assert note is not None
    assert "CLAUDE is soft-disabled until cleared" in note
    assert "explicit targets still run" in note

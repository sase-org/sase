"""Snapshot tests for the ``$`` link-follow reveal toast copy.

Each test pins the exact ``(title, markup message)`` text the pure
formatter in ``sase.ace.tui.actions._link_follow_toast`` produces, plus the
unified failure copy. Every message is also parsed with Textual's markup
renderer, so unbalanced tags fail here instead of in the live toast.
"""

from __future__ import annotations

from textual.content import Content

from sase.ace.link_reveal_context import HiddenReason, RevealOutcome
from sase.ace.tui.actions._link_follow_toast import (
    REVEAL_TOAST_TIMEOUT,
    format_link_failure,
    format_reveal_toast,
)
from sase.ace.tui.keymaps.display import key_display_name
from sase.ace.tui.widgets.artifacts.shell import build_reveal_chip_label


def _user_scenario() -> RevealOutcome:
    """The design's example: a closed phase revealed through its epic."""
    return RevealOutcome(
        pane_label="Bead",
        ref="bead:sase-16n.7",
        old_canonical="-status:closed limit:100",
        new_canonical="id:sase-16n.* limit:100",
        hidden=HiddenReason(kind="filtered", terms=("-status:closed",)),
        scope_change=None,
        context_label="epic sase-16n",
        outcome="context",
    )


def _assert_valid_markup(message: str) -> str:
    return Content.from_markup(message).plain


def test_user_scenario_toast_matches_design() -> None:
    title, message = format_reveal_toast(
        _user_scenario(),
        restore_key=key_display_name("circumflex_accent"),
        back_key=key_display_name("ctrl+o"),
        accent="#D787FF",
    )
    assert key_display_name("circumflex_accent") == "^"
    assert title == "↪ Bead sase-16n.7"
    assert message == (
        "query  [bold #D787FF]id:sase-16n.* limit:100[/]\n"
        "[dim]was    -status:closed limit:100 · hidden by [bold]-status:closed[/][/]\n"
        "epic sase-16n · ^ restore · Ctrl+O back"
    )
    plain = _assert_valid_markup(message)
    assert "id:sase-16n.* limit:100" in plain
    assert "epic sase-16n · ^ restore · Ctrl+O back" in plain


def test_boolean_hidden_reason_says_hidden_by_your_query() -> None:
    outcome = RevealOutcome(
        pane_label="Agent",
        ref="agent:sase-16n.7",
        old_canonical="(name:foo AND status:open)",
        new_canonical="(name:sase-16n OR name:sase-16n.*)",
        hidden=HiddenReason(kind="filtered_boolean"),
        scope_change=None,
        context_label="sase-16n hood",
        outcome="context",
    )
    title, message = format_reveal_toast(
        outcome, restore_key="^", back_key="Ctrl+O", accent="#0062FF"
    )
    assert title == "↪ Agent sase-16n.7"
    assert "[dim]was    (name:foo AND status:open) · hidden by your query[/]" in message
    _assert_valid_markup(message)


def test_limited_hidden_reason_reports_the_cap() -> None:
    outcome = RevealOutcome(
        pane_label="Bead",
        ref="bead:sase-abc",
        old_canonical="limit:10",
        new_canonical="id:sase-abc limit:10",
        hidden=HiddenReason(kind="limited", cap=10),
        scope_change=None,
        context_label="bead sase-abc",
        outcome="context",
    )
    _, message = format_reveal_toast(
        outcome, restore_key="^", back_key="Ctrl+O", accent="#D787FF"
    )
    assert "[dim]was    limit:10 · past limit:10[/]" in message
    _assert_valid_markup(message)


def test_unloaded_hidden_reason_uses_the_hint() -> None:
    outcome = RevealOutcome(
        pane_label="Bead",
        ref="bead:sase-abc",
        old_canonical="limit:100",
        new_canonical="id:sase-abc limit:100",
        hidden=HiddenReason(kind="unloaded", hint="row is not loaded"),
        scope_change=None,
        context_label=None,
        outcome="identity",
    )
    _, message = format_reveal_toast(
        outcome, restore_key="^", back_key="Ctrl+O", accent="#D787FF"
    )
    assert "[dim]was    limit:100 · row is not loaded[/]" in message
    # No context label: the key line still names the real restore/back keys.
    assert "^ restore · Ctrl+O back" in message
    _assert_valid_markup(message)


def test_optional_scope_fetched_and_fallback_lines() -> None:
    outcome = RevealOutcome(
        pane_label="Stitch",
        ref="stitch:sase@0123456789abcdef",
        old_canonical="repo:sase since:24h",
        new_canonical="repo:sase since:2026-09-01 until:2026-09-01",
        hidden=HiddenReason(kind="filtered", terms=("since:24h",)),
        scope_change=("sase", None),
        context_label="sase · 2026-09-01",
        hydrated=True,
        agents_tab_fallback=False,
        outcome="context",
    )
    title, message = format_reveal_toast(
        outcome, restore_key="^", back_key="Ctrl+O", accent="#FFD700"
    )
    assert title == "↪ Stitch sase@0123456"
    assert "scope  sase → All projects" in message
    assert "fetched  outside the loaded rows" in message
    _assert_valid_markup(message)


def test_agents_tab_fallback_line() -> None:
    outcome = RevealOutcome(
        pane_label="Agent",
        ref="agent:hidden-agent",
        old_canonical="status:open",
        new_canonical="name:hidden-agent",
        hidden=HiddenReason(kind="filtered", terms=("status:open",)),
        scope_change=None,
        context_label="agent hidden-agent",
        hydrated=False,
        agents_tab_fallback=True,
        outcome="identity",
    )
    _, message = format_reveal_toast(
        outcome, restore_key="^", back_key="Ctrl+O", accent="#0062FF"
    )
    assert "Agents tab filter hides it — showing Artifacts ▸ Agent" in message
    _assert_valid_markup(message)


def test_unknown_keys_are_dropped_never_guessed() -> None:
    _, message = format_reveal_toast(
        _user_scenario(), restore_key="", back_key="", accent="#D787FF"
    )
    assert message.splitlines()[-1] == "epic sase-16n"
    _assert_valid_markup(message)


def test_dynamic_values_are_escaped() -> None:
    outcome = RevealOutcome(
        pane_label="Bead",
        ref="bead:sase-16n.7",
        old_canonical="[evil] limit:100",
        new_canonical="id:sase-16n.* limit:100",
        hidden=HiddenReason(kind="filtered", terms=("[evil]",)),
        scope_change=("[sase]", None),
        context_label="[epic]",
        outcome="context",
    )
    _, message = format_reveal_toast(
        outcome, restore_key="^", back_key="Ctrl+O", accent="#D787FF"
    )
    assert "\\[evil]" in message
    assert "\\[epic]" in message
    assert "\\[sase]" in message
    # Escaping round-trips: the hostile values survive as literal text,
    # never as markup tags.
    plain = _assert_valid_markup(message)
    assert "[evil] limit:100" in plain
    assert "[epic]" in plain
    assert "[sase]" in plain


def test_reveal_toast_timeout_is_about_eight_seconds() -> None:
    assert REVEAL_TOAST_TIMEOUT == 8.0


def test_failure_copy_names_artifact_and_gives_one_reason() -> None:
    assert format_link_failure("dangling", ref="bug:missing") == (
        "No such artifact: missing",
        "No pane resolves bug:missing; the link may be stale or mistyped.",
        "warning",
    )
    assert format_link_failure("load", ref="bead:sase-ug.9", pane_label="Bead") == (
        "Cannot load sase-ug.9",
        "Bead failed to load for bead:sase-ug.9.",
        "error",
    )
    assert format_link_failure(
        "unconfigured", ref="research:notes", pane_label="Research"
    ) == (
        "Cannot follow notes",
        "The Research pane is not configured; configure its provider to enable this link.",
        "warning",
    )
    assert format_link_failure("missing", ref="bead:sase-ug.9", pane_label="Bead") == (
        "Not in Bead: sase-ug.9",
        "Bead has no bead:sase-ug.9 in its inventory.",
        "warning",
    )


def test_chip_label_carries_the_context_label() -> None:
    assert (
        build_reveal_chip_label("bead:sase-16n.7", "epic sase-16n")
        == "sase-16n.7 · epic sase-16n"
    )
    assert build_reveal_chip_label("bead:sase-16n.7", None) == "sase-16n.7"

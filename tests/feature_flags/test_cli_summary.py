"""Coverage for ``sase flag list`` summary presentation."""

from __future__ import annotations

import io

from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.bead.flag_due import FlagRemovalState
from sase.bead_flag_presentation import FLAG_DUE_GLYPH, FLAG_DUE_STYLES
from sase.feature_flags.cli_render import (
    FLAG_DISABLED_STYLE,
    FLAG_ENABLED_STYLE,
    FLAG_KIND_STYLE,
    enabled_text,
    kind_text,
)
from sase.feature_flags.cli_summary import (
    flag_list_summary_line,
    summarize_flag_views,
)
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import FeatureFlagDecision, FlagKind, FlagSource
from tests.feature_flags._helpers import demo_flag, flag_bead

_MIXED_FOOTER = (
    "3 flags · 2 beta  1 sunset · 2 on  1 off · 1 overridden · "
    f"{FLAG_DUE_GLYPH} 1 soon  {FLAG_DUE_GLYPH} 1 due"
)


def _view(
    key: str,
    *,
    kind: FlagKind = "beta",
    enabled: bool | None = None,
    overridden: bool = False,
    due_state: FlagRemovalState | None = None,
    source: FlagSource = "default",
) -> FlagView:
    definition = demo_flag(key, kind=kind)
    resolved_enabled = definition.default if enabled is None else enabled
    return FlagView(
        definition=definition,
        decision=FeatureFlagDecision(
            key=key,
            enabled=resolved_enabled,
            default=definition.default,
            source=source,
            source_detail="",
            overridden=overridden,
        ),
        bead=None,
        due_state=due_state,
    )


def _plain(text: Text) -> str:
    buf = io.StringIO()
    Console(file=buf, color_system=None, highlight=False, width=160).print(text)
    return buf.getvalue()


def _exact_span_style(text: Text, token: str) -> Style:
    matches = [
        Style.parse(str(span.style))
        for span in text.spans
        if text.plain[span.start : span.end] == token
    ]
    assert matches, f"no exact span {token!r} in {text.plain!r}"
    return matches[0]


def test_summary_counts_mixed_inventory_and_renders_the_canonical_footer() -> None:
    views = (
        _view("sunset_due", kind="sunset", due_state="due"),
        _view("beta_soon", enabled=True, overridden=True, due_state="soon"),
        _view("beta_live", due_state="live"),
    )

    summary = summarize_flag_views(views)

    assert summary.total == 3
    assert summary.by_kind == {"beta": 2, "sunset": 1}
    assert summary.enabled == 2
    assert summary.disabled == 1
    assert summary.overridden == 1
    assert summary.by_due == {"live": 1, "soon": 1, "due": 1}
    footer = flag_list_summary_line(summary)
    assert footer.plain == _MIXED_FOOTER


def test_summary_folds_homogeneous_kind_and_value() -> None:
    one = summarize_flag_views((_view("solo", enabled=True),))
    two = summarize_flag_views((_view("a", enabled=False), _view("b", enabled=False)))

    assert flag_list_summary_line(one).plain == "1 on beta flag"
    assert flag_list_summary_line(two).plain == "2 off beta flags"


def test_summary_partially_folds_homogeneous_kind_or_value() -> None:
    mixed_values = summarize_flag_views(
        (_view("on_flag", enabled=True), _view("off_flag", enabled=False))
    )
    mixed_kinds = summarize_flag_views(
        (
            _view("beta_on", enabled=True),
            _view("sunset_on", kind="sunset", enabled=True),
        )
    )

    assert flag_list_summary_line(mixed_values).plain == ("2 beta flags · 1 on  1 off")
    assert flag_list_summary_line(mixed_kinds).plain == (
        "2 on flags · 1 beta  1 sunset"
    )


def test_summary_honors_overridden_when_value_matches_default() -> None:
    view = _view(
        "beta_default",
        enabled=False,
        overridden=True,
        source="env",
    )

    summary = summarize_flag_views((view,))

    assert view.decision.enabled == view.decision.default
    assert summary.overridden == 1
    assert flag_list_summary_line(summary).plain == ("1 off beta flag · 1 overridden")


def test_summary_counts_due_states_from_views_without_recomputing() -> None:
    live_looking_bead = flag_bead(
        "mismatch",
        remove_by_date="2099-01-01",
        remove_by_release="9.99.0",
    )
    views = (
        FlagView(
            definition=demo_flag("mismatch"),
            decision=FeatureFlagDecision(
                key="mismatch",
                enabled=False,
                default=False,
                source="default",
                source_detail="",
                overridden=False,
            ),
            bead=live_looking_bead,
            due_state="due",
        ),
        _view("soon", due_state="soon"),
        _view("live", due_state="live"),
        _view("absent", due_state=None),
    )

    summary = summarize_flag_views(views)
    footer = flag_list_summary_line(summary)

    assert summary.by_due == {"live": 1, "soon": 1, "due": 1}
    assert "live" not in footer.plain
    assert f"{FLAG_DUE_GLYPH} 1 soon" in footer.plain
    assert f"{FLAG_DUE_GLYPH} 1 due" in footer.plain
    assert "0 soon" not in footer.plain
    assert "0 due" not in footer.plain


def test_summary_omits_urgency_when_only_live_due_states_are_present() -> None:
    summary = summarize_flag_views((_view("live", due_state="live"),))

    assert summary.by_due == {"live": 1, "soon": 0, "due": 0}
    assert flag_list_summary_line(summary).plain == "1 off beta flag"


def test_summary_footer_reuses_row_value_styles_and_urgency_styles() -> None:
    footer = flag_list_summary_line(
        summarize_flag_views(
            (
                _view("sunset_due", kind="sunset", due_state="due"),
                _view("beta_soon", enabled=True, overridden=True, due_state="soon"),
                _view("beta_live", due_state="live"),
            )
        )
    )

    assert _exact_span_style(footer, "beta") == Style.parse(FLAG_KIND_STYLE)
    assert _exact_span_style(footer, "sunset") == Style.parse(FLAG_KIND_STYLE)
    assert _exact_span_style(footer, "on") == Style.parse(FLAG_ENABLED_STYLE)
    assert _exact_span_style(footer, "off") == Style.parse(FLAG_DISABLED_STYLE)
    assert _exact_span_style(footer, "1 overridden") == Style.parse("bold")
    glyph_styles = [
        Style.parse(str(span.style))
        for span in footer.spans
        if footer.plain[span.start : span.end] == FLAG_DUE_GLYPH
    ]
    assert Style.parse(FLAG_DUE_STYLES["soon"].rich) in glyph_styles
    assert Style.parse(FLAG_DUE_STYLES["due"].rich) in glyph_styles
    assert kind_text("beta").plain == "beta"
    assert enabled_text(True).plain == "on"
    assert enabled_text(False).plain == "off"


def test_summary_footer_colorless_console_keeps_semantic_plain_text() -> None:
    footer = flag_list_summary_line(
        summarize_flag_views(
            (
                _view("sunset_due", kind="sunset", due_state="due"),
                _view("beta_soon", enabled=True, overridden=True, due_state="soon"),
                _view("beta_live", due_state="live"),
            )
        )
    )
    rendered = _plain(footer)

    assert "\x1b" not in rendered
    assert _MIXED_FOOTER in rendered


def test_summary_builder_may_return_zero_flags() -> None:
    summary = summarize_flag_views(())

    assert summary.total == 0
    assert summary.by_kind == {"beta": 0, "sunset": 0}
    assert summary.by_due == {"live": 0, "soon": 0, "due": 0}
    assert flag_list_summary_line(summary).plain == "0 flags"

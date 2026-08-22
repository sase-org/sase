"""Tests for ``sase flag list``."""

from __future__ import annotations

import io
import json
from datetime import date

import pytest
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.bead_flag_presentation import FLAG_DUE_GLYPH
from sase.feature_flags.beads import FlagBeadSnapshot
from sase.feature_flags.cli_list import (
    _LIST_JSON_SCHEMA_VERSION,
    _list_row,
    handle_flag_list,
)
from sase.feature_flags.cli_render import (
    FLAG_DISABLED_STYLE,
    FLAG_ENABLED_STYLE,
    FLAG_KIND_STYLE,
    enabled_text,
    kind_text,
)
from sase.feature_flags.cli_views import flag_views
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import FeatureFlagDefinition, FeatureFlagDiagnostic
from sase.main.parser import create_parser
from tests.feature_flags._helpers import (
    definitions,
    demo_flag,
    flag_bead,
    snapshot_for,
)
from tests.main.parser_help_helpers import parser_for


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=160, color_system=None, highlight=False), buf


def test_flag_list_empty_registry_prints_scaffold_hint() -> None:
    console, buf = _console()
    args = create_parser().parse_args(["flag", "list"])

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions={},
        snapshot=snapshot_for(),
        beads=(),
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "No feature flags are registered." in out
    assert "sase flag new" in out
    assert "is_sase_managed" in out
    assert "0 flags" not in out
    assert "\x1b" not in out


def test_flag_list_row_includes_env_provenance_and_countdown() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "list"])

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": True},
            source="env",
            source_detail=SASE_FEATURE_FLAGS_ENV,
        ),
        beads=(flag_bead("demo_flag"),),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "demo_flag" in out
    assert "beta" in out
    assert "default=off" in out
    assert "on" in out
    assert f"ENV:{SASE_FEATURE_FLAGS_ENV}" in out
    assert "sase-nb.test" in out
    assert "open" in out
    assert "v0.19.0" in out


def test_flag_list_surfaces_deprecated_env_diagnostic() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag", kind="sunset")
    args = create_parser().parse_args(["flag", "list"])

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": False},
            source="env",
            source_detail="SASE_DISABLE_DEMO",
            diagnostics=(
                FeatureFlagDiagnostic(
                    severity="warning",
                    code="deprecated_env",
                    message=(
                        "SASE_DISABLE_DEMO is deprecated; set feature flag "
                        "'demo_flag' via SASE_FEATURE_FLAGS or config instead"
                    ),
                    source="SASE_DISABLE_DEMO",
                ),
            ),
        ),
        beads=(flag_bead("demo_flag"),),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "ENV:SASE_DISABLE_DEMO" in out
    assert "deprecated" in out
    assert "SASE_DISABLE_DEMO" in out


def test_flag_list_row_includes_cli_provenance() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "list"])

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": True},
            source="cli",
            source_detail="--enable-feature",
        ),
        beads=(flag_bead("demo_flag"),),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "demo_flag" in out
    assert "CLI:--enable-feature" in out


def test_flag_list_json_payload(capsys: pytest.CaptureFixture[str]) -> None:
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "list", "--json"])

    handle_flag_list(
        args,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(flag),
        beads=(flag_bead("demo_flag"),),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert _LIST_JSON_SCHEMA_VERSION == 1
    assert payload["schema_version"] == _LIST_JSON_SCHEMA_VERSION
    assert set(payload) == {"diagnostics", "flags", "schema_version"}
    assert payload["flags"][0]["key"] == "demo_flag"
    assert payload["flags"][0]["bead"] == "sase-nb.test"
    assert payload["flags"][0]["due_state"] == "live"
    assert payload["flags"][0]["saved"] is None
    assert payload["flags"][0]["source"] == "default"
    assert " · " not in out
    assert f"{FLAG_DUE_GLYPH} 1" not in out


_MIXED_LIST_FOOTER = (
    "3 flags · 2 beta  1 sunset · 2 on  1 off · 1 overridden · "
    f"{FLAG_DUE_GLYPH} 1 soon  {FLAG_DUE_GLYPH} 1 due"
)


def _exact_span_style(text: Text, token: str) -> Style:
    matches = [
        Style.parse(str(span.style))
        for span in text.spans
        if text.plain[span.start : span.end] == token
    ]
    assert matches, f"no exact span {token!r} in {text.plain!r}"
    return matches[0]


def _mixed_list_flags() -> tuple[
    FeatureFlagDefinition, FeatureFlagDefinition, FeatureFlagDefinition
]:
    return (
        demo_flag("alpha_on", kind="beta", bead="sase-nb.soon"),
        demo_flag("beta_off", kind="beta", bead="sase-nb.live"),
        demo_flag("zeta_on", kind="sunset", bead="sase-nb.due"),
    )


def _mixed_list_beads() -> tuple[FlagBeadSnapshot, FlagBeadSnapshot, FlagBeadSnapshot]:
    return (
        flag_bead(
            "alpha_on",
            bead_id="sase-nb.soon",
            remove_by_date="2026-08-01",
            remove_by_release="0.19.0",
        ),
        flag_bead(
            "beta_off",
            bead_id="sase-nb.live",
            remove_by_date="2026-12-01",
            remove_by_release="0.19.0",
        ),
        flag_bead(
            "zeta_on",
            bead_id="sase-nb.due",
            kind="sunset",
            remove_by_date="2026-08-01",
            remove_by_release="0.16.0",
        ),
    )


def test_flag_list_help_documents_statistics_footer() -> None:
    help_text = parser_for(("sase", "flag", "list")).format_help()

    assert "statistics footer" in help_text
    assert "overridden" in help_text
    assert "soon or due" in help_text
    assert "2 beta  1 sunset" in help_text
    assert "--json" in help_text
    assert "does not include this footer" in help_text


def test_flag_list_nonempty_ends_with_blank_line_separated_footer() -> None:
    console, buf = _console()
    flags = _mixed_list_flags()
    args = create_parser().parse_args(["flag", "list"])

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions=definitions(*flags),
        snapshot=snapshot_for(*flags, enabled={"alpha_on": True}),
        beads=_mixed_list_beads(),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    lines = out.splitlines()
    assert lines[-1] == _MIXED_LIST_FOOTER
    assert lines[-2] == ""
    assert lines[-3]
    assert "\x1b" not in out
    assert out.count(_MIXED_LIST_FOOTER) == 1


def test_flag_list_diagnostics_stay_before_the_footer() -> None:
    console, buf = _console()
    flags = _mixed_list_flags()
    args = create_parser().parse_args(["flag", "list"])
    warning = (
        "SASE_DISABLE_PRETTIER is deprecated; set feature flag "
        "'prettier_enabled' via SASE_FEATURE_FLAGS or config instead"
    )

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions=definitions(*flags),
        snapshot=snapshot_for(
            *flags,
            enabled={"alpha_on": True},
            diagnostics=(
                FeatureFlagDiagnostic(
                    severity="warning",
                    code="deprecated_env",
                    message=warning,
                    source="SASE_DISABLE_PRETTIER",
                ),
            ),
        ),
        beads=_mixed_list_beads(),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    lines = buf.getvalue().splitlines()
    warning_lines = [index for index, line in enumerate(lines) if "deprecated" in line]
    assert warning_lines
    assert lines[-1] == _MIXED_LIST_FOOTER
    assert lines[-2] == ""
    assert warning_lines[-1] < len(lines) - 1


def test_flag_list_row_reuses_shared_kind_and_value_styles() -> None:
    on_flag = demo_flag("demo_on")
    off_flag = demo_flag("demo_off")
    today = date(2026, 8, 16)
    release = "0.16.0"
    on_view = flag_views(
        definitions={str(on_flag.key): on_flag},
        snapshot=snapshot_for(on_flag, enabled={"demo_on": True}),
        beads=(flag_bead("demo_on"),),
        today=today,
        release=release,
    )[0]
    off_view = flag_views(
        definitions={str(off_flag.key): off_flag},
        snapshot=snapshot_for(off_flag),
        beads=(flag_bead("demo_off"),),
        today=today,
        release=release,
    )[0]

    on_row = _list_row(on_view, today=today, release=release)
    off_row = _list_row(off_view, today=today, release=release)

    assert _exact_span_style(on_row, "beta") == Style.parse(FLAG_KIND_STYLE)
    assert _exact_span_style(on_row, "on") == Style.parse(FLAG_ENABLED_STYLE)
    assert _exact_span_style(off_row, "off") == Style.parse(FLAG_DISABLED_STYLE)
    assert kind_text("beta").plain == "beta"
    assert enabled_text(True).plain == "on"
    assert enabled_text(False).plain == "off"
    assert "beta" in on_row.plain
    assert "default=off" in on_row.plain
    assert "default=off" in off_row.plain


def test_flag_list_json_includes_saved_without_renaming_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "list", "--json"])

    handle_flag_list(
        args,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": True},
            source="state",
            source_detail="/tmp/feature_flags.json",
            saved={"demo_flag": True},
            state_path="/tmp/feature_flags.json",
        ),
        beads=(flag_bead("demo_flag"),),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"diagnostics", "flags", "schema_version"}
    assert payload["flags"][0]["source"] == "state"
    assert payload["flags"][0]["source_detail"] == "/tmp/feature_flags.json"
    assert payload["flags"][0]["saved"] is True
    assert payload["flags"][0]["enabled"] is True


def test_flag_list_renders_saved_provenance() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag")
    args = create_parser().parse_args(["flag", "list"])
    state_path = "/tmp/feature_flags.json"

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": True},
            source="state",
            source_detail=state_path,
            saved={"demo_flag": True},
            state_path=state_path,
        ),
        beads=(flag_bead("demo_flag"),),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "SAVED:" in out
    assert state_path in out

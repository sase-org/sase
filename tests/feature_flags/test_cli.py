"""Tests for ``sase flag`` list, show, new, and parser wiring."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from rich.console import Console

from sase.bead.model import FlagRecord, Issue, IssueType
from sase.bead.project import BeadProject
from sase.feature_flags.beads import create_flag_bead
from sase.feature_flags.cli_list import _LIST_JSON_SCHEMA_VERSION, handle_flag_list
from sase.feature_flags.cli_new import _build_flag_scaffold, handle_flag_new
from sase.feature_flags.cli_show import handle_flag_show
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import FeatureFlagDiagnostic, FeatureFlagError
from sase.feature_flags.references import FlagCallSite
from sase.main.parser import create_parser, default_list_delegation_notice
from tests.feature_flags._helpers import (
    demo_flag,
    flag_bead,
    snapshot_for,
)
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=160, color_system=None, highlight=False), buf


def test_flag_group_defaults_to_list() -> None:
    parser = create_parser()
    omitted = parser.parse_args(["flag"])
    explicit = parser.parse_args(["flag", "list"])

    assert omitted.flag_subcommand == "list"
    assert omitted.json is False
    assert default_list_delegation_notice(omitted) == (
        "No subcommand provided for 'sase flag'; delegating to 'sase flag list'."
    )
    assert default_list_delegation_notice(explicit) is None


def test_flag_help_lists_sorted_subcommands_and_managed_gate() -> None:
    flag_parser = parser_for(("sase", "flag"))
    help_text = flag_parser.format_help()
    expected = {"list", "new", "show"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "{list,new,show}" in help_text
    assert "is_sase_managed" in help_text
    assert "defaults to `sase flag list`" in help_text
    assert "sase/memory/sase_flags.md" not in help_text


def test_flag_new_help_documents_optional_flags_with_short_aliases() -> None:
    help_text = flat_help(parser_for(("sase", "flag", "new")).format_help())

    assert "-d, --description" in help_text
    assert "-k, --kind" in help_text
    assert "-r, --remove-by" in help_text
    assert "-s, --scope" in help_text
    assert "-z, --size" in help_text
    assert "is_sase_managed" in help_text
    assert "sase/memory/sase_flags.md" not in help_text


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


def test_flag_list_row_includes_env_provenance_and_countdown() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag", scope="global")
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
    assert "global" in out
    assert "sase-nb.test" in out
    assert "open" in out
    assert "v0.19.0" in out


def test_flag_list_surfaces_deprecated_env_diagnostic() -> None:
    console, buf = _console()
    flag = demo_flag("prettier_enabled", default=True, scope="global")
    args = create_parser().parse_args(["flag", "list"])

    exit_code = handle_flag_list(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(
            flag,
            enabled={"prettier_enabled": False},
            source="env",
            source_detail="SASE_DISABLE_PRETTIER",
            diagnostics=(
                FeatureFlagDiagnostic(
                    severity="warning",
                    code="deprecated_env",
                    message=(
                        "SASE_DISABLE_PRETTIER is deprecated; set feature flag "
                        "'prettier_enabled' via SASE_FEATURE_FLAGS or config instead"
                    ),
                    source="SASE_DISABLE_PRETTIER",
                ),
            ),
        ),
        beads=(flag_bead("prettier_enabled"),),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "ENV:SASE_DISABLE_PRETTIER" in out
    assert "deprecated" in out
    assert "SASE_DISABLE_PRETTIER" in out


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

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == _LIST_JSON_SCHEMA_VERSION
    assert payload["flags"][0]["key"] == "demo_flag"
    assert payload["flags"][0]["bead"] == "sase-nb.test"
    assert payload["flags"][0]["due_state"] == "live"


def test_flag_show_unknown_key_errors(capsys: pytest.CaptureFixture[str]) -> None:
    args = create_parser().parse_args(["flag", "show", "missing_flag"])

    exit_code = handle_flag_show(args, definitions={}, snapshot=snapshot_for())

    assert exit_code == 1
    assert "unknown feature flag: missing_flag" in capsys.readouterr().err


def test_flag_show_includes_layers_bead_and_call_sites() -> None:
    console, buf = _console()
    flag = demo_flag("demo_flag", scope="global")
    args = create_parser().parse_args(["flag", "show", "demo_flag"])

    exit_code = handle_flag_show(
        args,
        console=console,
        definitions={str(flag.key): flag},
        snapshot=snapshot_for(flag, enabled={"demo_flag": True}, source="user"),
        beads=(flag_bead("demo_flag"),),
        layers=(),
        call_sites=(
            FlagCallSite(
                path="consumer.py",
                line=12,
                text="return snapshot.enabled(FeatureFlag.demo_flag)",
            ),
        ),
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "demo_flag" in out
    assert "kind:" in out
    assert "VALUE" in out
    assert "LAYERS" in out
    assert "BEAD" in out
    assert "sase-nb.test" in out
    assert "2026-12-01" in out
    assert "CALL SITES" in out
    assert "consumer.py:12" in out


def test_flag_new_requires_sase_managed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.feature_flags.cli_new.project_is_sase_managed", lambda _cwd=None: False
    )
    args = create_parser().parse_args(["flag", "new", "demo_key"])

    exit_code = handle_flag_new(args, create_bead=False)

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "is_sase_managed" in err
    assert "sase/memory/sase_flags.md" not in err


def test_flag_new_scaffold_prints_registry_entry_and_checklist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.feature_flags.cli_new.project_is_sase_managed", lambda _cwd=None: True
    )
    console, buf = _console()
    args = create_parser().parse_args(
        ["flag", "new", "demo_key", "-d", "Opt-in beta", "-k", "beta"]
    )

    exit_code = handle_flag_new(
        args,
        console=console,
        definitions={},
        today=date(2026, 8, 16),
        version="0.16.0",
        create_bead=False,
    )

    assert exit_code == 0
    out = buf.getvalue()
    assert "demo_key = 'demo_key'" in out
    assert "kind='beta'" in out
    assert "description='Opt-in beta'" in out
    assert "bead='<flag-bead-id>'" in out
    assert "remove_by: 2026-11-14 / 0.18.0" in out
    assert "Both-states test checklist" in out
    assert "enabled=true" in out
    assert "enabled=false" in out
    assert "sase/memory/sase_flags.md" not in out


def test_flag_new_rejects_unknown_key_shape() -> None:
    with pytest.raises(FeatureFlagError, match="snake_case"):
        _build_flag_scaffold("NotAKey", create_bead=False, definitions={})


def test_flag_new_rejects_duplicate_registry_key() -> None:
    flag = demo_flag("demo_flag")
    with pytest.raises(FeatureFlagError, match="already registered"):
        _build_flag_scaffold(
            "demo_flag",
            create_bead=False,
            definitions={str(flag.key): flag},
        )


def test_flag_new_ops_requires_rationale() -> None:
    with pytest.raises(FeatureFlagError, match="rationale"):
        _build_flag_scaffold("ops_flag", kind="ops", create_bead=False, definitions={})


def test_flag_new_creates_a_flag_bead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.feature_flags.cli_new.project_is_sase_managed", lambda _cwd=None: True
    )
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)
    console, buf = _console()
    args = create_parser().parse_args(["flag", "new", "demo_key"])

    exit_code = handle_flag_new(
        args,
        console=console,
        definitions={},
        today=date(2026, 8, 16),
        version="0.16.0",
        cwd=tmp_path,
    )

    assert exit_code == 0
    with BeadProject(tmp_path) as project:
        issues = project.list_issues(issue_types=[IssueType.FLAG])
    assert len(issues) == 1
    assert issues[0].flag is not None
    assert issues[0].flag.key == "demo_key"
    assert issues[0].flag.remove_by_date == "2026-11-14"
    assert issues[0].flag.remove_by_release == "0.18.0"
    assert f"Created flag bead: {issues[0].id}" in buf.getvalue()
    assert f"bead={issues[0].id!r}" in buf.getvalue()


def test_flag_new_reports_the_committed_bead_id_after_remint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.feature_flags.cli_new.project_is_sase_managed", lambda _cwd=None: True
    )
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)

    stale_id = "sase-nv"
    real_create = BeadProject.create

    def create_returning_stale_id(
        self: BeadProject, *args: object, **kwargs: object
    ) -> Issue:
        issue = real_create(self, *args, **kwargs)
        assert issue.id != stale_id
        return replace(issue, id=stale_id)

    monkeypatch.setattr(BeadProject, "create", create_returning_stale_id)

    created: list[Issue] = []
    real_create_flag_bead = create_flag_bead

    def capture_create_flag_bead(*args: object, **kwargs: object) -> Issue:
        issue = real_create_flag_bead(*args, **kwargs)
        created.append(issue)
        return issue

    monkeypatch.setattr(
        "sase.feature_flags.cli_new.create_flag_bead", capture_create_flag_bead
    )

    console, buf = _console()
    args = create_parser().parse_args(["flag", "new", "demo_key"])

    exit_code = handle_flag_new(
        args,
        console=console,
        definitions={},
        today=date(2026, 8, 16),
        version="0.16.0",
        cwd=tmp_path,
    )

    assert exit_code == 0
    with BeadProject(tmp_path) as project:
        issues = project.list_issues(issue_types=[IssueType.FLAG])
    assert len(issues) == 1
    committed_id = issues[0].id
    assert committed_id != stale_id
    assert len(created) == 1
    assert created[0].id == committed_id
    out = buf.getvalue()
    assert f"Created flag bead: {committed_id}" in out
    assert f"bead={committed_id!r}" in out
    assert stale_id not in out


def test_create_flag_bead_fails_when_committed_bead_cannot_be_reread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.feature_flags.beads.load_flag_bead_snapshots",
        lambda cwd=None: (),
    )

    with pytest.raises(
        FeatureFlagError,
        match="was not found after the store mutation committed",
    ):
        create_flag_bead(
            FlagRecord(
                key="demo_key",
                remove_by_date="2026-11-14",
                remove_by_release="0.18.0",
            ),
            title="Retire demo_key",
            cwd=tmp_path,
        )


def test_flag_new_ops_skips_bead_and_uses_description_as_rationale() -> None:
    text = _build_flag_scaffold(
        "ops_flag",
        kind="ops",
        description="Operational escape hatch",
        create_bead=False,
        definitions={},
    )

    assert "No flag bead created" in text
    assert "bead=None" in text
    assert "rationale='Operational escape hatch'" in text
    assert "remove_by:" not in text

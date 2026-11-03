"""Unit coverage for Justfile ``--epic-symbol`` discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.epic_symbols import (
    _EpicSymbolEntry,
    _LeftoverEpicSymbolsError,
    _leftover_epic_symbols_for_close,
    parse_epic_symbol_entries,
    discover_justfile,
    entries_for_beads,
    raise_if_leftover_epic_symbols,
    raise_if_surviving_flag_definition,
)
from sase.bead.model import Issue, IssueType, Status


def _issue(issue_id: str, *, status: Status = Status.IN_PROGRESS) -> Issue:
    return Issue(
        id=issue_id,
        title=issue_id,
        issue_type=IssueType.PLAN,
        status=status,
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
    )


def _flag_issue(issue_id: str, *, status: Status = Status.IN_PROGRESS) -> Issue:
    return Issue(
        id=issue_id,
        title=issue_id,
        issue_type=IssueType.TASK,
        status=status,
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
        task_type="flag",
    )


def _write_flag_registry(root: Path, text: str) -> Path:
    (root / ".git").mkdir(exist_ok=True)
    (root / "Justfile").write_text("check:\n", encoding="utf-8")
    registry = root / "src/sase/feature_flags/registry.py"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(text, encoding="utf-8")
    return registry


_REGISTRY_WITH_ABC = """
_FEATURE_FLAG_DEFINITIONS = {
    FeatureFlag.old_path: FeatureFlagDefinition(
        key=FeatureFlag.old_path,
        kind="sunset",
        description="Old path.",
        bead="sase-abc",
    ),
}
"""


def testparse_epic_symbol_entries_accepts_quoted_and_bare_flags() -> None:
    text = """
        --epic-symbol "sase-nb(encode_feature_flags_env)" \\
        --epic-symbol 'sase-o8.4(PlaceholderRankingMetadata)' \\
        --epic-symbol=sase-n4(UsageLimitSettings) \\
        --epic-symbol sase-n4.5(ProviderDisableWriteOutcome) \\
        --epic-symbol "not-a-body"
    """

    parsed = parse_epic_symbol_entries(text, source=Path("Justfile"))

    assert [entry.raw for entry in parsed] == [
        "sase-nb(encode_feature_flags_env)",
        "sase-o8.4(PlaceholderRankingMetadata)",
        "sase-n4(UsageLimitSettings)",
        "sase-n4.5(ProviderDisableWriteOutcome)",
    ]
    assert parsed[0].flag == '--epic-symbol "sase-nb(encode_feature_flags_env)"'
    assert parsed[1].bead_id == "sase-o8.4"
    assert parsed[1].symbol == "PlaceholderRankingMetadata"


def test_entries_for_beads_include_descendant_suffixes_only() -> None:
    entries = parse_epic_symbol_entries(
        """
        --epic-symbol "sase-o8(CommonIndex)"
        --epic-symbol "sase-o8.3(RankedPlaceholder)"
        --epic-symbol "sase-o8.4(load_common_placeholder_index)"
        --epic-symbol "sase-o9.2(monitor_row_agent_name)"
        """
    )

    epic = [entry.raw for entry in entries_for_beads(entries, ["sase-o8"])]
    phase = [entry.raw for entry in entries_for_beads(entries, ["sase-o8.3"])]

    assert epic == [
        "sase-o8(CommonIndex)",
        "sase-o8.3(RankedPlaceholder)",
        "sase-o8.4(load_common_placeholder_index)",
    ]
    assert phase == ["sase-o8.3(RankedPlaceholder)"]


def test_leftover_epic_symbols_skip_already_closed_targets() -> None:
    entries = [
        _EpicSymbolEntry(bead_id="sase-o8.2", symbol="CommonPlaceholderIndex"),
    ]

    leftovers = _leftover_epic_symbols_for_close(
        [_issue("sase-o8.2", status=Status.CLOSED)],
        entries,
    )

    assert leftovers == []


def testdiscover_justfile_stops_at_git_root_without_crossing_it(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    nested = repo / "src"
    nested.mkdir()

    assert discover_justfile(nested) is None

    justfile = repo / "Justfile"
    justfile.write_text('--epic-symbol "sase-x(Foo)"\n', encoding="utf-8")

    assert discover_justfile(nested) == justfile


def test_raise_if_leftover_epic_symbols_names_the_justfile_flags(
    tmp_path: Path,
) -> None:
    (tmp_path / "Justfile").write_text(
        '--epic-symbol "sase-o8.2(CommonPlaceholderIndex)"\n'
        '--epic-symbol "sase-o8.2(load_common_placeholder_index)"\n',
        encoding="utf-8",
    )

    with pytest.raises(
        _LeftoverEpicSymbolsError, match="refusing to close"
    ) as exc_info:
        raise_if_leftover_epic_symbols(
            [_issue("sase-o8.2")],
            start=tmp_path,
        )

    message = str(exc_info.value)
    assert '--epic-symbol "sase-o8.2(CommonPlaceholderIndex)"' in message
    assert '--epic-symbol "sase-o8.2(load_common_placeholder_index)"' in message
    assert "sase bead epic-symbols sase-o8.2" in message


def test_raise_if_surviving_flag_definition_names_flag_key_and_fix(
    tmp_path: Path,
) -> None:
    _write_flag_registry(tmp_path, _REGISTRY_WITH_ABC)

    with pytest.raises(_LeftoverEpicSymbolsError, match="rule 7") as exc_info:
        raise_if_surviving_flag_definition([_flag_issue("sase-abc")], start=tmp_path)

    message = str(exc_info.value)
    assert "refusing to close sase-abc" in message
    assert "old_path (bead=sase-abc)" in message
    assert "delete each flag's Off branch" in message
    assert "keep the bead open" in message


def test_raise_if_surviving_flag_definition_allows_close_once_entry_is_removed(
    tmp_path: Path,
) -> None:
    registry = _write_flag_registry(tmp_path, _REGISTRY_WITH_ABC)
    registry.write_text("_FEATURE_FLAG_DEFINITIONS = {}\n", encoding="utf-8")

    raise_if_surviving_flag_definition([_flag_issue("sase-abc")], start=tmp_path)


def test_raise_if_surviving_flag_definition_ignores_other_and_closed_beads(
    tmp_path: Path,
) -> None:
    _write_flag_registry(tmp_path, _REGISTRY_WITH_ABC)

    raise_if_surviving_flag_definition([_flag_issue("sase-other")], start=tmp_path)
    raise_if_surviving_flag_definition(
        [_flag_issue("sase-abc", status=Status.CLOSED)], start=tmp_path
    )
    raise_if_surviving_flag_definition([_issue("sase-abc")], start=tmp_path)


def test_raise_if_surviving_flag_definition_ignores_comments_and_docstrings(
    tmp_path: Path,
) -> None:
    _write_flag_registry(
        tmp_path,
        '"""Example: FeatureFlagDefinition(key=..., bead="sase-abc")."""\n'
        '# bead="sase-abc" was removed\n',
    )

    raise_if_surviving_flag_definition([_flag_issue("sase-abc")], start=tmp_path)


def test_raise_if_surviving_flag_definition_skips_missing_registry(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "Justfile").write_text("check:\n", encoding="utf-8")

    raise_if_surviving_flag_definition([_flag_issue("sase-abc")], start=tmp_path)


def test_surviving_refusal_names_scanned_checkout(tmp_path: Path) -> None:
    _write_flag_registry(tmp_path, _REGISTRY_WITH_ABC)

    with pytest.raises(_LeftoverEpicSymbolsError, match="rule 7") as exc_info:
        raise_if_surviving_flag_definition(
            [_flag_issue("sase-abc")],
            start=tmp_path,
            start_source="local",
        )

    message = str(exc_info.value)
    assert str(tmp_path) in message
    assert "refusing to close sase-abc" in message


def test_surviving_refusal_explains_primary_fallback(tmp_path: Path) -> None:
    _write_flag_registry(tmp_path, _REGISTRY_WITH_ABC)

    with pytest.raises(_LeftoverEpicSymbolsError) as exc_info:
        raise_if_surviving_flag_definition(
            [_flag_issue("sase-abc")],
            start=tmp_path,
            start_source="primary",
        )

    message = str(exc_info.value)
    assert "fell back to the primary workspace" in message
    assert "run the close from the checkout that removed" in message


def test_surviving_refusal_mentions_gate_workspace(tmp_path: Path) -> None:
    _write_flag_registry(tmp_path, _REGISTRY_WITH_ABC)

    with pytest.raises(_LeftoverEpicSymbolsError) as exc_info:
        raise_if_surviving_flag_definition(
            [_flag_issue("sase-abc")],
            start=tmp_path,
            start_source="gate",
        )

    message = str(exc_info.value)
    assert "SASE_GATE_WORKSPACE_DIR" in message
    assert str(tmp_path) in message


def test_gate_inherited_checkout_close_succeeds_while_primary_defines_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from sase.bead.cli_location import BeadsLocation
    from sase.bead.operation_context import (
        BeadOperationContext,
        symbol_scan_start_detail_for_operation_context,
    )
    from sase.workspace_provider import ownership

    primary = tmp_path / "primary"
    gate = tmp_path / "gate"
    bundle = tmp_path / "bundle"
    for directory in (primary, gate, bundle):
        directory.mkdir()
    _write_flag_registry(primary, _REGISTRY_WITH_ABC)
    _write_flag_registry(gate, "_FEATURE_FLAG_DEFINITIONS = {}\n")
    location = BeadsLocation(primary, "sdd/beads")
    context = BeadOperationContext(
        invocation_cwd=bundle.resolve(),
        location=location,
        project_key=None,
        project_label=None,
        primary_workspace=primary.resolve(),
        ownership_context=None,
    )

    def fake_user_directed_context(
        *,
        cwd: Path | None = None,
        project: object = None,
        project_file: object = None,
        config: object = None,
        env: object = None,
    ) -> object:
        del project, project_file, config, env
        resolved = Path(cwd).expanduser().resolve(strict=False)
        if resolved == bundle.resolve():
            from sase.workspace_provider._ownership_types import (
                WorkspaceOwnershipError,
            )

            raise WorkspaceOwnershipError("no checkout at bundle")
        return SimpleNamespace(
            checkout_dir=gate.resolve(),
            primary_checkout_dir=primary.resolve(),
            project="sase",
        )

    monkeypatch.setattr(ownership, "user_directed_context", fake_user_directed_context)
    monkeypatch.setenv("SASE_GATE_COMMAND", "1")
    monkeypatch.setenv("SASE_GATE_WORKSPACE_DIR", str(gate.resolve()))

    start, source = symbol_scan_start_detail_for_operation_context(context)
    assert start == gate.resolve()
    assert source == "gate"
    # The inherited checkout removed the definition, so the guard passes
    # even though the primary checkout still defines it.
    raise_if_surviving_flag_definition(
        [_flag_issue("sase-abc")], start=start, start_source=source
    )

    with pytest.raises(_LeftoverEpicSymbolsError, match="rule 7"):
        raise_if_surviving_flag_definition(
            [_flag_issue("sase-abc")], start=primary.resolve(), start_source="primary"
        )

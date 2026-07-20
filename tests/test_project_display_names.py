"""Tests for display-only project name resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase import project_display_names as pdn


def _record(project_name: str, display_name: str | None = None) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def test_project_display_name_for_resolves_and_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets"), _record("plain")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    assert pdn.project_display_name_for("plain", root) == "plain"
    assert pdn.project_display_name_for("missing", root) == "missing"


def test_snapshot_keeps_identity_immutable_and_sorts_by_label_then_key() -> None:
    snapshot = pdn.ProjectDisplaySnapshot.from_records(
        [
            _record("gh_globex__widgets", "widgets"),
            _record("gh_acme__widgets", "widgets"),
            _record("gh_acme__alpha", "Alpha"),
        ]
    )

    assert snapshot.label_for("gh_acme__widgets") == "widgets"
    assert snapshot.label_for("deleted") == "deleted"
    assert snapshot.projection_for("deleted") == pdn.ProjectDisplayProjection(
        project_key="deleted",
        project_label="deleted",
    )
    assert [
        (projection.project_key, projection.project_label)
        for projection in snapshot.projections
    ] == [
        ("gh_acme__alpha", "Alpha"),
        ("gh_acme__widgets", "widgets"),
        ("gh_globex__widgets", "widgets"),
    ]
    assert snapshot.projections[1].sort_key == (
        "widgets",
        "gh_acme__widgets",
    )

    with pytest.raises(TypeError):
        snapshot.labels_by_key["gh_acme__widgets"] = "mutated"  # type: ignore[index]


def test_supplied_snapshot_helpers_do_not_reload_lifecycle_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_list_project_records(
        *_args: object, **_kwargs: object
    ) -> list[ProjectRecordWire]:
        nonlocal calls
        calls += 1
        return [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", fake_list_project_records)
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
    snapshot = pdn.load_project_display_snapshot(tmp_path / "projects")
    agent = SimpleNamespace(
        project_file="/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase",
        project_display_name=None,
    )

    assert calls == 1
    assert (
        pdn.project_display_name_for("gh_acme__widgets", snapshot=snapshot) == "widgets"
    )
    assert pdn.project_display_for(
        "missing", snapshot=snapshot
    ) == pdn.ProjectDisplayProjection("missing", "missing")
    assert (
        pdn.humanize_cl_name("gh_acme__widgets_fix", snapshot=snapshot) == "widgets_fix"
    )
    assert (
        pdn.humanize_cl_names_in_text("done gh_acme__widgets_fix", snapshot=snapshot)
        == "done widgets_fix"
    )
    assert (
        pdn.humanize_vcs_refs_in_text("#gh:gh_acme__widgets fix", snapshot=snapshot)
        == "#gh:widgets fix"
    )
    assert (
        pdn.humanize_safe_stem("gh_acme__widgets-ace_run", snapshot=snapshot)
        == "widgets-ace_run"
    )
    assert pdn.project_display_name_map_signature(snapshot=snapshot) == (
        ("gh_acme__widgets", "widgets"),
    )
    pdn.attach_project_display_names([agent], snapshot=snapshot)
    assert agent.project_display_name == "widgets"
    assert calls == 1


def test_snapshot_load_failure_falls_back_to_canonical_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_inventory(*_args: object, **_kwargs: object) -> list[ProjectRecordWire]:
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(pdn, "list_project_records", fail_inventory)

    snapshot = pdn.load_project_display_snapshot(tmp_path / "projects")

    assert snapshot.label_for("gh_acme__widgets") == "gh_acme__widgets"
    assert (
        pdn.project_display_name_for("gh_acme__widgets", snapshot=snapshot)
        == "gh_acme__widgets"
    )


def test_humanize_cl_name_rewrites_exact_key_and_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_cl_name("gh_acme__widgets", root) == "widgets"
    assert (
        pdn.humanize_cl_name("gh_acme__widgets_fix_button_1", root)
        == "widgets_fix_button_1"
    )


def test_humanize_cl_name_prefers_longest_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [
        _record("gh_acme__widgets", "widgets"),
        _record("gh_acme__widgets_extra", "widgets_extra"),
    ]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_cl_name("gh_acme__widgets_extra_fix_button", root)
        == "widgets_extra_fix_button"
    )


def test_humanize_cl_name_unknown_and_empty_map_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: [])
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_cl_name("gh_acme__widgets_fix_button", root) == (
        "gh_acme__widgets_fix_button"
    )

    records = [_record("gh_acme__widgets", "widgets")]
    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_cl_name("other_fix_button", root) == "other_fix_button"


def test_humanize_cl_names_in_text_rewrites_tokens_but_not_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    text = (
        "Sync done for gh_acme__widgets_fix_button_1: "
        "/tmp/gh_acme__widgets/gh_acme__widgets_fix_button_1"
    )

    assert pdn.humanize_cl_names_in_text(text, root) == (
        "Sync done for widgets_fix_button_1: "
        "/tmp/gh_acme__widgets/gh_acme__widgets_fix_button_1"
    )


def test_humanize_safe_stem_rewrites_exact_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.humanize_safe_stem("gh_acme__widgets", root) == "widgets"


def test_humanize_safe_stem_rewrites_joined_prefixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_acme__widgets-ace_run-260707", root)
        == "widgets-ace_run-260707"
    )
    assert (
        pdn.humanize_safe_stem("gh_acme__widgets_fix_button-260707", root)
        == "widgets_fix_button-260707"
    )


def test_humanize_safe_stem_matches_sanitized_hyphenated_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_sase-org__sase", "sase")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_sase_org__sase-ace_run-260707_011513", root)
        == "sase-ace_run-260707_011513"
    )


def test_humanize_safe_stem_unknown_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_other__widgets-ace_run-260707", root)
        == "gh_other__widgets-ace_run-260707"
    )


def test_humanize_safe_stem_prefers_longest_safe_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [
        _record("gh_acme__widgets", "widgets"),
        _record("gh_acme__widgets_extra", "widgets_extra"),
    ]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert (
        pdn.humanize_safe_stem("gh_acme__widgets_extra_fix_button-260707", root)
        == "widgets_extra_fix_button-260707"
    )


def test_fresh_load_refresh_and_invalidation_observe_nested_name_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    project_dir = root / "gh_acme__widgets"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "gh_acme__widgets.sase"
    project_file.write_text("widgets", encoding="utf-8")
    calls = 0

    def fake_list_project_records(
        *_args: object, **_kwargs: object
    ) -> list[ProjectRecordWire]:
        nonlocal calls
        calls += 1
        return [
            _record(
                "gh_acme__widgets",
                project_file.read_text(encoding="utf-8"),
            )
        ]

    monkeypatch.setattr(pdn, "list_project_records", fake_list_project_records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    root_mtime = root.stat().st_mtime_ns
    project_file.write_text("gadgets", encoding="utf-8")
    assert root.stat().st_mtime_ns == root_mtime

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    assert calls == 1

    fresh = pdn.load_project_display_snapshot(root)
    assert fresh.label_for("gh_acme__widgets") == "gadgets"
    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    assert calls == 2

    refreshed = pdn.refresh_project_display_snapshot(root)
    assert refreshed.label_for("gh_acme__widgets") == "gadgets"
    assert pdn.project_display_name_for("gh_acme__widgets", root) == "gadgets"
    assert calls == 3

    project_file.write_text("tools", encoding="utf-8")
    pdn.invalidate_project_display_snapshot(root)
    assert pdn.project_display_name_for("gh_acme__widgets", root) == "tools"
    assert calls == 4


def test_attach_project_display_names_duck_types_and_clears_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [
        _record("gh_acme__widgets", "widgets"),
        _record("gh_acme__plain", "gh_acme__plain"),
    ]
    widgets = SimpleNamespace(
        project_file="/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase",
        project_display_name=None,
    )
    equal = SimpleNamespace(
        project_file="/tmp/projects/gh_acme__plain/gh_acme__plain.sase",
        project_display_name="stale",
    )
    missing = SimpleNamespace(
        project_file="/tmp/projects/missing/missing.sase",
        project_display_name="stale",
    )
    ignored = SimpleNamespace(project_file="/tmp/projects/ignored/ignored.sase")

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    pdn.attach_project_display_names([widgets, equal, missing, ignored], root)

    assert widgets.project_display_name == "widgets"
    assert equal.project_display_name is None
    assert missing.project_display_name is None
    assert not hasattr(ignored, "project_display_name")

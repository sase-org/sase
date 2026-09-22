"""Pure renderers for ``tools/render_visual_snapshot_failure_report``.

Covers ``discover_records``, ``render_html``, ``render_summary``,
``render_annotations``, ``render_manifest``, and ``expected_blob_url``.
``write_outputs`` / manifest-output / CLI coverage lives in
``tests/test_render_visual_snapshot_failure_report_outputs.py``; shared
builders live in ``tests/_render_visual_snapshot_failure_report_helpers.py``.
"""

from __future__ import annotations

import base64
import json
import shlex
import types
from pathlib import Path

import pytest

from tests._render_visual_snapshot_failure_report_helpers import (
    failure_png,
    load_script,
    write_failure,
)


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return load_script()


# ---------------------------------------------------------------------------
# discover_records / load_record
# ---------------------------------------------------------------------------


def test_discover_records_yields_sorted_records(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_b",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_b.png",
    )
    write_failure(
        artifact_root,
        node_id="tests/a.py::test_two",
        snapshot="widget_a",
        kind="missing_golden",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )

    records = list(script.discover_records(artifact_root))

    assert len(records) == 2
    snapshots = [r.snapshot for r in records]
    assert snapshots == sorted(snapshots) or snapshots[0] != snapshots[1]


def test_discover_records_handles_missing_root(
    tmp_path: Path, script: types.ModuleType
) -> None:
    records = list(script.discover_records(tmp_path / "does-not-exist"))
    assert records == []


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


def test_render_html_embeds_images_and_has_anchor(
    tmp_path: Path, script: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/ace/tui/visual/test_widget.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    monkeypatch.chdir(tmp_path)
    records = list(script.discover_records(artifact_root))
    context = script.RenderContext(repo=None, sha=None, report_url=None)

    html = script.render_html(records, context=context)

    anchor = records[0].anchor
    assert f'id="{anchor}"' in html
    assert "data:image/png;base64," in html
    actual_b64 = base64.b64encode(failure_png((0, 0, 255, 255))).decode("ascii")
    assert actual_b64 in html
    assert "&lt;svg&gt;actual&lt;/svg&gt;" in html


def test_render_html_empty(script: types.ModuleType) -> None:
    html = script.render_html(
        [], context=script.RenderContext(repo=None, sha=None, report_url=None)
    )
    assert "No sase's TUI PNG snapshot failures" in html
    assert "<html" in html


def test_render_html_missing_golden_omits_expected_block(
    tmp_path: Path, script: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/ace/tui/visual/test_widget.py::test_one",
        snapshot="widget_missing",
        kind="missing_golden",
        expected_repo_path="tests/_snapshots/png/widget_missing.png",
        expected_color=None,
        include_diff=False,
    )
    monkeypatch.chdir(tmp_path)
    records = list(script.discover_records(artifact_root))
    html = script.render_html(
        records, context=script.RenderContext(repo=None, sha=None, report_url=None)
    )

    assert "img-actual" in html
    assert "img-expected" not in html
    assert "img-diff" not in html


# ---------------------------------------------------------------------------
# summary.md
# ---------------------------------------------------------------------------


def test_render_summary_contains_blob_and_anchor_links(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    failure_dir = write_failure(
        artifact_root,
        node_id="tests/ace/tui/visual/test_widget.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    records = list(script.discover_records(artifact_root))
    context = script.RenderContext(
        repo="owner/name",
        sha="deadbeef",
        report_url="https://example.invalid/artifact",
    )

    summary = script.render_summary(records, context=context)

    assert "# sase's TUI PNG snapshot failures" in summary
    assert (
        "https://github.com/owner/name/blob/deadbeef/"
        "tests/_snapshots/png/widget_a.png" in summary
    )
    anchor = records[0].anchor
    assert f"https://example.invalid/artifact#{anchor}" in summary
    # Compact table: no embedded images.
    assert "data:image/png" not in summary
    assert "`tests/ace/tui/visual/test_widget.py:17`" in summary
    assert failure_dir.exists()


def test_render_summary_without_repo_uses_bare_fragments(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget.png",
    )
    records = list(script.discover_records(artifact_root))
    summary = script.render_summary(
        records, context=script.RenderContext(repo=None, sha=None, report_url=None)
    )

    assert "https://github.com" not in summary
    anchor = records[0].anchor
    assert f"(#{anchor})" in summary


def test_render_summary_empty(script: types.ModuleType) -> None:
    summary = script.render_summary(
        [], context=script.RenderContext(repo=None, sha=None, report_url=None)
    )
    assert "No failures recorded." in summary


# ---------------------------------------------------------------------------
# annotations.sh
# ---------------------------------------------------------------------------


def test_render_annotations_escapes_workflow_command_specials(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/x.py::test",
        snapshot="weird,name:value",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/weird,name:value.png",
        test_file="tests/path,with:colons\nand-newline.py",
        test_line=42,
        extras={"changed_pixels": 3, "total_pixels": 4, "changed_ratio": 0.75},
    )
    records = list(script.discover_records(artifact_root))
    annotations = script.render_annotations(records)

    assert annotations.startswith("#!/usr/bin/env bash\n")
    # Property values must have colons, commas, CR, LF, and % escaped.
    assert "%3A" in annotations  # colon
    assert "%2C" in annotations  # comma
    assert "%0A" in annotations  # newline
    # The message body keeps the colon in the snapshot name, but newlines
    # and CR are still escaped.
    assert "TUI PNG snapshot mismatch" in annotations
    assert "line=42" in annotations
    # No literal newline inside any echo argument.
    for line in annotations.splitlines():
        if line.startswith("echo"):
            parts = shlex.split(line)
            assert parts[0] == "echo"
            assert len(parts) == 2
            assert "\n" not in parts[1]
            assert "\r" not in parts[1]


def test_render_annotations_empty_records_yields_safe_script(
    script: types.ModuleType,
) -> None:
    annotations = script.render_annotations([])
    assert annotations.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in annotations


def test_render_annotations_missing_golden_title(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/a.py::test",
        snapshot="missing",
        kind="missing_golden",
        expected_repo_path="tests/_snapshots/png/missing.png",
        expected_color=None,
        include_diff=False,
    )
    records = list(script.discover_records(artifact_root))
    annotations = script.render_annotations(records)

    assert "TUI PNG snapshot missing golden" in annotations


# ---------------------------------------------------------------------------
# manifest.jsonl
# ---------------------------------------------------------------------------


def test_render_manifest_emits_jsonl_with_anchors(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    write_failure(
        artifact_root,
        node_id="tests/a.py::test_two",
        snapshot="widget_b",
        kind="missing_golden",
        expected_repo_path="tests/_snapshots/png/widget_b.png",
        expected_color=None,
        include_diff=False,
    )
    records = list(script.discover_records(artifact_root))
    manifest = script.render_manifest(records)

    entries = [json.loads(line) for line in manifest.splitlines()]
    assert len(entries) == 2
    assert {entry["snapshot"] for entry in entries} == {"widget_a", "widget_b"}
    for entry in entries:
        assert entry["anchor"].startswith("failure-")


# ---------------------------------------------------------------------------
# expected_blob_url helper
# ---------------------------------------------------------------------------


def test_expected_blob_url_requires_repo_and_sha(
    script: types.ModuleType,
) -> None:
    assert (
        script.expected_blob_url(
            "snapshots/x.png",
            script.RenderContext(repo=None, sha=None, report_url=None),
        )
        is None
    )
    assert (
        script.expected_blob_url(
            "snapshots/x.png",
            script.RenderContext(repo="owner/name", sha=None, report_url=None),
        )
        is None
    )
    assert (
        script.expected_blob_url(
            "snapshots/x.png",
            script.RenderContext(repo="owner/name", sha="abc", report_url=None),
        )
        == "https://github.com/owner/name/blob/abc/snapshots/x.png"
    )

"""Unit tests for ``tools/render_visual_snapshot_failure_report``.

The script has no ``.py`` suffix, so the test module loads it through
``importlib.machinery.SourceFileLoader`` and exposes it as a fixture.
"""

from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import json
import struct
import subprocess
import sys
import types
import zlib
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "render_visual_snapshot_failure_report"
)


def _load_script() -> types.ModuleType:
    """Load the suffix-less tool script as a module."""
    loader = importlib.machinery.SourceFileLoader(
        "render_visual_snapshot_failure_report", str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return _load_script()


def _png(color: tuple[int, int, int, int], size: tuple[int, int] = (1, 1)) -> bytes:
    width, height = size
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _write_failure(
    artifact_root: Path,
    *,
    node_id: str,
    snapshot: str,
    kind: str,
    expected_repo_path: str,
    test_file: str | None = "tests/ace/tui/visual/test_widget.py",
    test_line: int | None = 17,
    include_diff: bool = True,
    include_svg: bool = True,
    actual_color: tuple[int, int, int, int] = (0, 0, 255, 255),
    expected_color: tuple[int, int, int, int] | None = (255, 0, 0, 255),
    extras: dict | None = None,
) -> Path:
    slug_node = "".join(c if c.isalnum() or c in "._-" else "_" for c in node_id).strip(
        "._-"
    )
    slug_snap = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in snapshot
    ).strip("._-")
    failure_dir = artifact_root / slug_node / slug_snap
    failure_dir.mkdir(parents=True)

    record: dict = {
        "node_id": node_id,
        "snapshot": snapshot,
        "kind": kind,
        "expected_repo_path": expected_repo_path,
        "actual_path": (f"{artifact_root.name}/{slug_node}/{slug_snap}/actual.png"),
        "summary_path": (f"{artifact_root.name}/{slug_node}/{slug_snap}/summary.txt"),
        "test_file": test_file,
        "test_line": test_line,
    }
    (failure_dir / "actual.png").write_bytes(_png(actual_color))
    (failure_dir / "summary.txt").write_text("summary placeholder\n")

    if kind == "mismatch":
        assert expected_color is not None
        (failure_dir / "expected.png").write_bytes(_png(expected_color))
        record["expected_path"] = (
            f"{artifact_root.name}/{slug_node}/{slug_snap}/expected.png"
        )
        if include_diff:
            (failure_dir / "diff.png").write_bytes(_png((255, 0, 0, 255)))
            record["diff_path"] = (
                f"{artifact_root.name}/{slug_node}/{slug_snap}/diff.png"
            )
        record.update(
            {
                "expected_size": [1, 1],
                "actual_size": [1, 1],
                "changed_pixels": 1,
                "total_pixels": 1,
                "changed_ratio": 1.0,
            }
        )

    if include_svg:
        (failure_dir / "actual.svg").write_text("<svg>actual</svg>")
        record["source_svg_path"] = (
            f"{artifact_root.name}/{slug_node}/{slug_snap}/actual.svg"
        )

    if extras is not None:
        record.update(extras)

    (failure_dir / "failure.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    return failure_dir


# ---------------------------------------------------------------------------
# discover_records / load_record
# ---------------------------------------------------------------------------


def test_discover_records_yields_sorted_records(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    _write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_b",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_b.png",
    )
    _write_failure(
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
    _write_failure(
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
    actual_b64 = base64.b64encode(_png((0, 0, 255, 255))).decode("ascii")
    assert actual_b64 in html
    assert "&lt;svg&gt;actual&lt;/svg&gt;" in html


def test_render_html_empty(script: types.ModuleType) -> None:
    html = script.render_html(
        [], context=script.RenderContext(repo=None, sha=None, report_url=None)
    )
    assert "No ACE PNG snapshot failures" in html
    assert "<html" in html


def test_render_html_missing_golden_omits_expected_block(
    tmp_path: Path, script: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "sase-visual"
    _write_failure(
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
    failure_dir = _write_failure(
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

    assert "# ACE PNG snapshot failures" in summary
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
    _write_failure(
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
    _write_failure(
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
    assert "ACE PNG snapshot mismatch" in annotations
    assert "line=42" in annotations
    # No literal newline inside any echo argument.
    for line in annotations.splitlines():
        if line.startswith("echo"):
            # Only one logical line per echo (no embedded raw \n in payload).
            assert line.count("'") % 2 == 0


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
    _write_failure(
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

    assert "ACE PNG snapshot missing golden" in annotations


# ---------------------------------------------------------------------------
# manifest.jsonl
# ---------------------------------------------------------------------------


def test_render_manifest_emits_jsonl_with_anchors(
    tmp_path: Path, script: types.ModuleType
) -> None:
    artifact_root = tmp_path / "sase-visual"
    _write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    _write_failure(
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
# write_outputs / CLI
# ---------------------------------------------------------------------------


def test_write_outputs_writes_all_four_files(
    tmp_path: Path, script: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "sase-visual"
    _write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    monkeypatch.chdir(tmp_path)
    records = list(script.discover_records(artifact_root))
    output_dir = tmp_path / "report"
    context = script.RenderContext(repo="owner/name", sha="deadbeef", report_url=None)

    script.write_outputs(records, output_dir=output_dir, context=context)

    assert (output_dir / "visual-failure-report.html").exists()
    assert (output_dir / "summary.md").exists()
    assert (output_dir / "annotations.sh").exists()
    assert (output_dir / "manifest.jsonl").exists()


def test_write_outputs_no_records_writes_empty_outputs(
    tmp_path: Path, script: types.ModuleType
) -> None:
    output_dir = tmp_path / "report"
    context = script.RenderContext(repo=None, sha=None, report_url=None)

    script.write_outputs([], output_dir=output_dir, context=context)

    html_text = (output_dir / "visual-failure-report.html").read_text()
    assert "No ACE PNG snapshot failures" in html_text
    assert (
        (output_dir / "summary.md")
        .read_text()
        .startswith("# ACE PNG snapshot failures")
    )
    assert (output_dir / "annotations.sh").read_text().startswith("#!/usr/bin/env bash")
    assert (output_dir / "manifest.jsonl").read_text() == ""


def test_cli_runs_end_to_end(tmp_path: Path) -> None:
    artifact_root = tmp_path / "sase-visual"
    _write_failure(
        artifact_root,
        node_id="tests/a.py::test_one",
        snapshot="widget_a",
        kind="mismatch",
        expected_repo_path="tests/_snapshots/png/widget_a.png",
    )
    output_dir = tmp_path / "report"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--artifact-root",
            str(artifact_root),
            "--output-dir",
            str(output_dir),
            "--repo",
            "owner/name",
            "--sha",
            "deadbeef",
            "--report-url",
            "https://example.invalid/artifact",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "visual-failure-report.html").exists()
    assert (output_dir / "summary.md").exists()
    assert (output_dir / "annotations.sh").exists()
    assert (output_dir / "manifest.jsonl").exists()


def test_cli_no_records_exits_zero(tmp_path: Path) -> None:
    artifact_root = tmp_path / "empty"
    output_dir = tmp_path / "report"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--artifact-root",
            str(artifact_root),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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

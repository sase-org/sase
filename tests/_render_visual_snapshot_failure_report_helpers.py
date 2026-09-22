"""Shared builders for ``tools/render_visual_snapshot_failure_report`` tests.

The script has no ``.py`` suffix, so helpers load it through
``importlib.machinery.SourceFileLoader``. Test modules import
:func:`load_script` (via a local ``script`` fixture), :func:`failure_png`,
and :func:`write_failure` from here instead of duplicating them.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import struct
import sys
import zlib
from pathlib import Path
from types import ModuleType


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "render_visual_snapshot_failure_report"
)


def load_script() -> ModuleType:
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


def failure_png(
    color: tuple[int, int, int, int], size: tuple[int, int] = (1, 1)
) -> bytes:
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


def write_failure(
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
    (failure_dir / "actual.png").write_bytes(failure_png(actual_color))
    (failure_dir / "summary.txt").write_text("summary placeholder\n")

    if kind == "mismatch":
        assert expected_color is not None
        (failure_dir / "expected.png").write_bytes(failure_png(expected_color))
        record["expected_path"] = (
            f"{artifact_root.name}/{slug_node}/{slug_snap}/expected.png"
        )
        if include_diff:
            (failure_dir / "diff.png").write_bytes(failure_png((255, 0, 0, 255)))
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

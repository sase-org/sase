from __future__ import annotations

import hashlib
from pathlib import Path

from sase.memory.episodes.source_refs import build_source_ref, normalize_source_path


def test_build_source_ref_hashes_existing_file(tmp_path: Path) -> None:
    source_path = tmp_path / "source.md"
    source_path.write_text("hello\n", encoding="utf-8")

    ref = build_source_ref(source_path, "chat", label="source")

    assert ref.id.startswith("src-")
    assert ref.kind == "chat"
    assert ref.path == normalize_source_path(source_path)
    assert ref.label == "source"
    assert ref.exists is True
    assert ref.size_bytes == len("hello\n")
    assert ref.sha256 == hashlib.sha256(b"hello\n").hexdigest()


def test_build_source_ref_preserves_missing_source(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.diff"

    ref = build_source_ref(missing_path, "artifact")

    assert ref.id.startswith("src-")
    assert ref.path == normalize_source_path(missing_path)
    assert ref.exists is False
    assert ref.size_bytes is None
    assert ref.sha256 is None

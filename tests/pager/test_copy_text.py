"""Unit tests for pager clipboard text without kind labels."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.pager.copy_text import (
    copy_text_for_reference,
    strip_reference_kind,
)

_DIGEST = "file:explicit:0123456789abcdef01234567"


def test_span_mode_strips_kind_labels() -> None:
    cases = {
        "file:/tmp/x.py": "/tmp/x.py",
        "file:/tmp/x.py:12": "/tmp/x.py:12",
        "@bead:sase-1": "sase-1",
        "bead:sase-uk.5": "sase-uk.5",
        "commit:abc1234": "abc1234",
        "stitch:sase@abc1234": "sase@abc1234",
        "plan:202609/x.md#L3": "202609/x.md#L3",
    }
    for ref, expected in cases.items():
        assert strip_reference_kind(ref) == expected
        assert copy_text_for_reference(ref) == expected


def test_gated_mode_requires_known_kinds() -> None:
    assert (
        strip_reference_kind("plan:202609/x.md", known_kinds=("plan",)) == "202609/x.md"
    )
    assert (
        copy_text_for_reference("plan:202609/x.md", known_kinds=("plan",))
        == "202609/x.md"
    )
    assert (
        strip_reference_kind("plan:202609/x.md", known_kinds=()) == "plan:202609/x.md"
    )
    assert (
        copy_text_for_reference("plan:202609/x.md", known_kinds=())
        == "plan:202609/x.md"
    )
    assert (
        strip_reference_kind("abc1234:src/x.py", known_kinds=()) == "abc1234:src/x.py"
    )
    assert strip_reference_kind("ambiguous:src/x", known_kinds=()) == "ambiguous:src/x"
    assert strip_reference_kind("bead:sase-1", known_kinds=()) == "sase-1"


def test_never_touched() -> None:
    for ref in (
        "/tmp/x.py",
        "src/x.py:12",
        "https://example.test/a",
        "#sase_plan",
        "",
    ):
        assert strip_reference_kind(ref) == ref
        assert copy_text_for_reference(ref) == ref
        assert copy_text_for_reference(ref, known_kinds=()) == ref


def test_pinned_version_keeps_sha_colon_path_shape() -> None:
    stripped = strip_reference_kind("file:/tmp/x.py", known_kinds=())
    assert f"abc1234:{stripped}" == "abc1234:/tmp/x.py"


def test_digest_resolves_to_stored_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = tmp_path / "stored.md"
    stored.write_text("stored\n", encoding="utf-8")

    def fake_resolve(value: str, *, context: object = None) -> object:
        assert value == _DIGEST
        return object()

    def fake_path(_result: object) -> Path:
        return stored

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference", fake_resolve
    )
    monkeypatch.setattr("sase.artifact_cli.references.resolved_file_path", fake_path)

    assert copy_text_for_reference(_DIGEST) == str(stored)


def test_digest_failure_copies_canonical_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(value: str, *, context: object = None) -> object:
        raise ValueError("no such file")

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference", fake_resolve
    )

    assert copy_text_for_reference(_DIGEST) == _DIGEST


def test_digest_without_path_copies_canonical_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(value: str, *, context: object = None) -> object:
        return object()

    def fake_path(_result: object) -> None:
        return None

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference", fake_resolve
    )
    monkeypatch.setattr("sase.artifact_cli.references.resolved_file_path", fake_path)

    copied = copy_text_for_reference(_DIGEST)
    assert copied == _DIGEST
    assert copied != "explicit:0123456789abcdef01234567"

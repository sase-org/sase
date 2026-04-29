"""Tests for compute_deltas() and the status-letter mapping helper."""

from pathlib import Path
from typing import Any

import pytest

from sase.ace.changespec.models import ChangeSpec, DeltaEntry
from sase.ace.deltas import (
    DeltaComputationError,
    apply_status_mapping,
    compute_deltas,
)
from sase.vcs_provider import VCSOperationError, VCSProvider


def _make_changespec(
    name: str,
    parent: str | None = None,
    project: str = "myproject",
    tmp_path: Path | None = None,
) -> ChangeSpec:
    file_path = (
        str(tmp_path / project / f"{project}.gp")
        if tmp_path
        else f"/tmp/{project}/{project}.gp"
    )
    return ChangeSpec(
        name=name,
        description="x",
        parent=parent,
        cl=None,
        status="Draft",
        test_targets=None,
        kickstart=None,
        file_path=file_path,
        line_number=1,
    )


class _FakeProvider(VCSProvider):
    """Minimal VCSProvider stub for compute_deltas() tests."""

    def __init__(
        self,
        diff_result: list[tuple[str, str]] | Exception,
        default_parent: str = "origin/main",
        resolved: dict[str, str] | None = None,
    ) -> None:
        self._diff_result = diff_result
        self._default_parent = default_parent
        self._resolved = resolved or {}
        self.calls: dict[str, Any] = {}

    # --- only methods compute_deltas needs ---
    def diff_name_status(
        self, parent_ref: str, head_ref: str, cwd: str
    ) -> list[tuple[str, str]]:
        self.calls["diff_name_status"] = (parent_ref, head_ref, cwd)
        if isinstance(self._diff_result, Exception):
            raise self._diff_result
        return self._diff_result

    def get_default_parent_revision(self, cwd: str) -> str:
        return self._default_parent

    def resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        return self._resolved.get(changespec_name, changespec_name)

    # --- abstract stubs (unused) ---
    def checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def diff(self, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def diff_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def apply_patch(self, patch_path: str, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def apply_patches(
        self, patch_paths: list[str], cwd: str
    ) -> tuple[bool, str | None]:
        raise NotImplementedError

    def add_remove(self, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def clean_workspace(self, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def commit(self, name: str, logfile: str, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def amend(
        self, note: str, cwd: str, *, no_upload: bool = False
    ) -> tuple[bool, str | None]:
        raise NotImplementedError

    def rename_branch(self, new_name: str, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def rebase(
        self, branch_name: str, new_parent: str, cwd: str
    ) -> tuple[bool, str | None]:
        raise NotImplementedError

    def archive(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def prune(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        raise NotImplementedError

    def stash_and_clean(
        self, diff_name: str, cwd: str, *, timeout: int = 300
    ) -> tuple[bool, str | None]:
        raise NotImplementedError


# ----------------------------------------------------------------------
# apply_status_mapping
# ----------------------------------------------------------------------


def test_apply_status_mapping_passes_known_letters_through() -> None:
    raw = [("A", "new.py"), ("M", "edit.py"), ("D", "gone.py")]
    assert apply_status_mapping(raw) == [
        DeltaEntry(path="edit.py", change_type="M"),
        DeltaEntry(path="gone.py", change_type="D"),
        DeltaEntry(path="new.py", change_type="A"),
    ]


def test_apply_status_mapping_splits_renames_into_delete_plus_add() -> None:
    raw = [("R100", "old/path.py\tnew/path.py")]
    assert apply_status_mapping(raw) == [
        DeltaEntry(path="new/path.py", change_type="A"),
        DeltaEntry(path="old/path.py", change_type="D"),
    ]


def test_apply_status_mapping_copy_emits_target_only() -> None:
    raw = [("C75", "src.py\tcopy.py")]
    # Source is unchanged in the parent, so don't surface it as deleted.
    assert apply_status_mapping(raw) == [
        DeltaEntry(path="copy.py", change_type="A"),
    ]


def test_apply_status_mapping_unknown_letter_coerces_to_modified(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = [("T", "switched_type.py"), ("U", "unmerged.py")]
    with caplog.at_level("WARNING"):
        result = apply_status_mapping(raw)
    assert result == [
        DeltaEntry(path="switched_type.py", change_type="M"),
        DeltaEntry(path="unmerged.py", change_type="M"),
    ]
    # Both unknown letters should warn.
    assert "switched_type.py" in caplog.text
    assert "unmerged.py" in caplog.text


def test_apply_status_mapping_sorted_alphabetically() -> None:
    raw = [("A", "z.py"), ("M", "a.py"), ("D", "m.py")]
    paths = [d.path for d in apply_status_mapping(raw)]
    assert paths == ["a.py", "m.py", "z.py"]


# ----------------------------------------------------------------------
# compute_deltas — ref selection + dispatch
# ----------------------------------------------------------------------


def test_compute_deltas_no_parent_uses_default_parent_ref() -> None:
    provider = _FakeProvider(
        diff_result=[("A", "f.py")],
        default_parent="origin/master",
        resolved={"my_cl": "feature-branch"},
    )
    cs = _make_changespec("my_cl", parent=None)
    result = compute_deltas(cs, provider, cwd="/repo")
    assert provider.calls["diff_name_status"] == (
        "origin/master",
        "feature-branch",
        "/repo",
    )
    assert result == [DeltaEntry(path="f.py", change_type="A")]


def test_compute_deltas_with_unknown_parent_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.deltas.compute.find_all_changespecs",
        lambda: [],
    )
    provider = _FakeProvider(
        diff_result=[],
        default_parent="origin/develop",
        resolved={"child": "child-branch"},
    )
    cs = _make_changespec("child", parent="missing_parent")
    compute_deltas(cs, provider, cwd="/repo")
    assert provider.calls["diff_name_status"][0] == "origin/develop"


def test_compute_deltas_with_known_parent_resolves_parent_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_cs = _make_changespec("parent_cl")
    monkeypatch.setattr(
        "sase.ace.deltas.compute.find_all_changespecs",
        lambda: [parent_cs],
    )
    provider = _FakeProvider(
        diff_result=[("M", "x.py")],
        resolved={"parent_cl": "parent-branch", "child_cl": "child-branch"},
    )
    cs = _make_changespec("child_cl", parent="parent_cl")
    compute_deltas(cs, provider, cwd="/repo")
    assert provider.calls["diff_name_status"] == (
        "parent-branch",
        "child-branch",
        "/repo",
    )


def test_compute_deltas_renames_split_correctly() -> None:
    provider = _FakeProvider(
        diff_result=[
            ("R100", "old.py\tnew.py"),
            ("M", "other.py"),
        ],
    )
    cs = _make_changespec("cl", parent=None)
    result = compute_deltas(cs, provider, cwd="/repo")
    assert result == [
        DeltaEntry(path="new.py", change_type="A"),
        DeltaEntry(path="old.py", change_type="D"),
        DeltaEntry(path="other.py", change_type="M"),
    ]


def test_compute_deltas_wraps_vcs_failure_in_typed_error() -> None:
    provider = _FakeProvider(
        diff_result=VCSOperationError("diff_name_status", "boom"),
    )
    cs = _make_changespec("cl", parent=None)
    with pytest.raises(DeltaComputationError) as exc:
        compute_deltas(cs, provider, cwd="/repo")
    assert exc.value.changespec_name == "cl"
    assert "boom" in str(exc.value)


def test_compute_deltas_wraps_not_implemented_in_typed_error() -> None:
    provider = _FakeProvider(
        diff_result=NotImplementedError("nope"),
    )
    cs = _make_changespec("cl", parent=None)
    with pytest.raises(DeltaComputationError):
        compute_deltas(cs, provider, cwd="/repo")

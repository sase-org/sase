"""Tests for ``sase changespec current``."""

from __future__ import annotations

import argparse
import json
from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.main.changespec_handler import _handle_current
from sase.main.parser import create_parser


class _FakeProvider:
    def __init__(self, *, branch: str | None = None, url: str | None = None) -> None:
        self.branch = branch
        self.url = url

    def get_branch_name(self, cwd: str) -> tuple[bool, str | None]:
        return (self.branch is not None, self.branch)

    def get_change_url(self, cwd: str) -> tuple[bool, str | None]:
        return (self.url is not None, self.url)

    def derive_branch_name(self, changespec_name: str, project_basename: str) -> str:
        return _strip_project_and_suffix(changespec_name, project_basename)

    def derive_branch_name_with_suffix(
        self, changespec_name: str, project_basename: str
    ) -> str:
        prefix = f"{project_basename}_"
        if changespec_name.startswith(prefix):
            return changespec_name[len(prefix) :]
        return changespec_name


def _strip_project_and_suffix(name: str, project: str) -> str:
    prefix = f"{project}_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    for sep in ("__", "_"):
        base, suffix = name.rsplit(sep, 1) if sep in name else (name, "")
        if suffix.isdigit():
            return base
    return name


def _cs(
    name: str,
    *,
    project: str = "proj",
    cl: str | None = None,
    status: str = "Ready",
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="test",
        parent="parent_spec",
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=f"/home/user/.sase/projects/{project}/{project}.gp",
        line_number=7,
    )


def _run_current(
    monkeypatch: Any,
    capsys: Any,
    *,
    changespecs: list[ChangeSpec],
    provider: _FakeProvider,
    project: str | None = "proj",
    output_format: str = "json",
    project_file: str | None = None,
) -> tuple[int, str, str]:
    monkeypatch.setattr(
        "sase.main.changespec_handler.find_all_changespecs",
        lambda: changespecs,
    )
    monkeypatch.setattr(
        "sase.main.changespec_handler.get_project_from_workspace",
        lambda: project,
    )
    monkeypatch.setattr(
        "sase.main.changespec_handler.get_vcs_provider",
        lambda cwd: provider,
    )
    args = argparse.Namespace(format=output_format, project_file=project_file)
    code = _handle_current(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_changespec_current_parser_accepts_format_short_flag() -> None:
    args = create_parser().parse_args(["changespec", "current", "-f", "json"])

    assert args.command == "changespec"
    assert args.changespec_subcommand == "current"
    assert args.format == "json"


def test_changespec_current_matches_provider_url(monkeypatch: Any, capsys: Any) -> None:
    url = "https://github.com/sase-org/sase/pull/123"
    code, out, err = _run_current(
        monkeypatch,
        capsys,
        changespecs=[
            _cs("proj_other", cl="https://github.com/sase-org/sase/pull/999"),
            _cs("proj_feature", cl=url),
        ],
        provider=_FakeProvider(branch="unrelated", url=url),
    )

    assert code == 0
    assert err == ""
    assert json.loads(out)["name"] == "proj_feature"


def test_changespec_current_matches_exact_branch(monkeypatch: Any, capsys: Any) -> None:
    code, out, err = _run_current(
        monkeypatch,
        capsys,
        changespecs=[_cs("proj_feature")],
        provider=_FakeProvider(branch="proj_feature"),
    )

    assert code == 0
    assert err == ""
    assert json.loads(out)["name"] == "proj_feature"


def test_changespec_current_matches_git_style_branch(
    monkeypatch: Any, capsys: Any
) -> None:
    code, out, err = _run_current(
        monkeypatch,
        capsys,
        changespecs=[_cs("proj_feature_work_1")],
        provider=_FakeProvider(branch="feature-work_1"),
    )

    assert code == 0
    assert err == ""
    assert json.loads(out)["name"] == "proj_feature_work_1"


def test_changespec_current_matches_project_prefix_stripped_branch(
    monkeypatch: Any, capsys: Any
) -> None:
    code, out, err = _run_current(
        monkeypatch,
        capsys,
        changespecs=[_cs("proj_feature_work_1")],
        provider=_FakeProvider(branch="feature_work_1"),
    )

    assert code == 0
    assert err == ""
    assert json.loads(out)["name"] == "proj_feature_work_1"


def test_changespec_current_no_match_diagnoses_context(
    monkeypatch: Any, capsys: Any
) -> None:
    code, out, err = _run_current(
        monkeypatch,
        capsys,
        changespecs=[_cs("proj_other")],
        provider=_FakeProvider(branch="missing", url="https://example.test/pr/1"),
    )

    assert code == 1
    assert out == ""
    assert "could not find a ChangeSpec" in err
    assert "project: proj" in err
    assert "branch: missing" in err
    assert "change_url: https://example.test/pr/1" in err


def test_changespec_current_ambiguous_match_fails(
    monkeypatch: Any, capsys: Any
) -> None:
    code, out, err = _run_current(
        monkeypatch,
        capsys,
        changespecs=[
            _cs("proj_feature_work_1"),
            _cs("proj_feature_work__1"),
        ],
        provider=_FakeProvider(branch="feature-work"),
    )

    assert code == 1
    assert out == ""
    assert "multiple ChangeSpecs match" in err
    assert "proj_feature_work_1" in err
    assert "proj_feature_work__1" in err

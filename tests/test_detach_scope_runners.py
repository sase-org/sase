"""Scheduler workflow, mentor, and checks runners escape the service cgroup."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.detach_scope import _DetachScopeCommand
from tests._detach_scope_helpers import escaped_launch, fake_popen_class, noop_launch


def test_crs_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return escaped_launch(list(argv))

    output_path = tmp_path / "crs.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", fake_popen_class(captured, pid=4321)
    )
    monkeypatch.setattr(starter, "claim_next_axe_workspace", lambda *a, **k: 10)
    monkeypatch.setattr(
        starter,
        "get_workspace_directory_for_num",
        lambda *a, **k: (str(tmp_path), None),
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "run_sase_hg_clean", lambda *a, **k: (True, None))
    monkeypatch.setattr(starter, "set_comment_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        starter,
        "transfer_workspace_claim",
        lambda *a, **k: _types.SimpleNamespace(success=True, error=None),
    )
    provider = _types.SimpleNamespace(
        stash_and_clean=lambda *a, **k: (True, None),
        resolve_revision=lambda *a, **k: "rev",
        checkout=lambda *a, **k: (True, None),
    )
    monkeypatch.setattr(starter, "get_vcs_provider", lambda *a, **k: provider)
    monkeypatch.setattr(
        "sase.workspace_provider.utils.parse_workspace_dir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr("sase.vcs_provider.detect_vcs_family", lambda *a: "hg")

    patch = _types.SimpleNamespace(
        name="cl1",
        file_path="proj.sase",
        project_basename="proj",
        comments=None,
    )
    comment = _types.SimpleNamespace(reviewer="critique", file_path="")
    result = starter._start_crs_workflow(patch, comment, lambda *a: None)  # noqa: SLF001

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE CRS runner",
        "unit_prefix": "sase-crs",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_crs_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return noop_launch(list(argv))

    output_path = tmp_path / "crs.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", fake_popen_class(captured, pid=4321)
    )
    monkeypatch.setattr(starter, "claim_next_axe_workspace", lambda *a, **k: 10)
    monkeypatch.setattr(
        starter,
        "get_workspace_directory_for_num",
        lambda *a, **k: (str(tmp_path), None),
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "run_sase_hg_clean", lambda *a, **k: (True, None))
    monkeypatch.setattr(starter, "set_comment_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        starter,
        "transfer_workspace_claim",
        lambda *a, **k: _types.SimpleNamespace(success=True, error=None),
    )
    provider = _types.SimpleNamespace(
        stash_and_clean=lambda *a, **k: (True, None),
        resolve_revision=lambda *a, **k: "rev",
        checkout=lambda *a, **k: (True, None),
    )
    monkeypatch.setattr(starter, "get_vcs_provider", lambda *a, **k: provider)
    monkeypatch.setattr(
        "sase.workspace_provider.utils.parse_workspace_dir", lambda *a: str(tmp_path)
    )
    monkeypatch.setattr("sase.vcs_provider.detect_vcs_family", lambda *a: "hg")

    patch = _types.SimpleNamespace(
        name="cl1",
        file_path="proj.sase",
        project_basename="proj",
        comments=None,
    )
    comment = _types.SimpleNamespace(reviewer="critique", file_path="")
    result = starter._start_crs_workflow(patch, comment, lambda *a: None)  # noqa: SLF001

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_fix_hook_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return escaped_launch(list(argv))

    output_path = tmp_path / "fix.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", fake_popen_class(captured, pid=4322)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: "")
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        "sase.ace.hooks.try_claim_hook_for_fix", lambda *a, **k: "summary"
    )

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter.start_fix_hook_workflow(patch, hook, "entry1", lambda *a: None)

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE fix-hook runner",
        "unit_prefix": "sase-fix-hook",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_fix_hook_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return noop_launch(list(argv))

    output_path = tmp_path / "fix.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", fake_popen_class(captured, pid=4322)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: "")
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)
    monkeypatch.setattr(
        "sase.ace.hooks.try_claim_hook_for_fix", lambda *a, **k: "summary"
    )

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter.start_fix_hook_workflow(patch, hook, "entry1", lambda *a: None)

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_summarize_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return escaped_launch(list(argv))

    hook_output = tmp_path / "hook-out.txt"
    hook_output.write_text("boom\n")
    output_path = tmp_path / "sum.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", fake_popen_class(captured, pid=4323)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: str(hook_output))
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter._start_summarize_hook_workflow(  # noqa: SLF001
        patch, hook, "entry1", lambda *a: None
    )

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE summarize runner",
        "unit_prefix": "sase-summarize",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_summarize_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.workflows_runner.starter as starter

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return noop_launch(list(argv))

    hook_output = tmp_path / "hook-out.txt"
    hook_output.write_text("boom\n")
    output_path = tmp_path / "sum.txt"
    monkeypatch.setattr(starter, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        starter.subprocess, "Popen", fake_popen_class(captured, pid=4323)
    )
    monkeypatch.setattr(starter, "generate_timestamp", lambda: "260921_120000")
    monkeypatch.setattr(
        starter, "get_workflow_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(starter, "get_hook_output_path", lambda *a: str(hook_output))
    monkeypatch.setattr(starter, "set_hook_suffix", lambda *a, **k: None)

    hook = _types.SimpleNamespace(
        command="myhook",
        display_command="myhook",
        get_status_line_for_stitch=lambda entry_id: _types.SimpleNamespace(
            timestamp="260921_120000"
        ),
    )
    patch = _types.SimpleNamespace(name="cl1", file_path="proj.sase", hooks=[])
    result = starter._start_summarize_hook_workflow(  # noqa: SLF001
        patch, hook, "entry1", lambda *a: None
    )

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_mentor_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.mentor_runner as mentor_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return escaped_launch(list(argv))

    output_path = tmp_path / "mentor.txt"
    monkeypatch.setattr(mentor_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        mentor_module.subprocess, "Popen", fake_popen_class(captured, pid=4324)
    )
    monkeypatch.setattr(
        mentor_module, "_get_mentor_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(mentor_module, "set_mentor_status", lambda *a, **k: None)

    patch = _types.SimpleNamespace(name="cl1", file_path="p.sase")
    profile = _types.SimpleNamespace(profile_name="prof")
    result = mentor_module.start_single_mentor(
        patch, "entry1", profile, "m1", lambda *a: None
    )

    assert result is not None
    assert captured["detach_kwargs"] == {
        "description": "SASE mentor runner",
        "unit_prefix": "sase-mentor",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_mentor_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types as _types

    import sase.ace.scheduler.mentor_runner as mentor_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return noop_launch(list(argv))

    output_path = tmp_path / "mentor.txt"
    monkeypatch.setattr(mentor_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        mentor_module.subprocess, "Popen", fake_popen_class(captured, pid=4324)
    )
    monkeypatch.setattr(
        mentor_module, "_get_mentor_output_path", lambda *a: str(output_path)
    )
    monkeypatch.setattr(mentor_module, "set_mentor_status", lambda *a, **k: None)

    patch = _types.SimpleNamespace(name="cl1", file_path="p.sase")
    profile = _types.SimpleNamespace(profile_name="prof")
    result = mentor_module.start_single_mentor(
        patch, "entry1", profile, "m1", lambda *a: None
    )

    assert result is not None
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True


def test_checks_runner_uses_detach_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.ace.scheduler.checks_runner as checks_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        captured["detach_kwargs"] = kwargs
        return escaped_launch(list(argv))

    monkeypatch.setattr(checks_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        checks_module.subprocess, "Popen", fake_popen_class(captured, pid=4325)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )

    output_path = tmp_path / "check.txt"
    assert (
        checks_module._start_background_check(  # noqa: SLF001
            "echo hi", str(output_path), str(tmp_path)
        )
        is True
    )
    assert captured["detach_kwargs"] == {
        "description": "SASE checks runner",
        "unit_prefix": "sase-checks",
    }
    assert captured["popen_argv"] == ["scope", *captured["detach_argv"]]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is False


def test_checks_runner_noop_outside_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sase.ace.scheduler.checks_runner as checks_module

    captured: dict[str, object] = {}

    def fake_detach_scope(argv: list[str], **kwargs: object) -> _DetachScopeCommand:
        captured["detach_argv"] = list(argv)
        return noop_launch(list(argv))

    monkeypatch.setattr(checks_module, "detach_scope", fake_detach_scope)
    monkeypatch.setattr(
        checks_module.subprocess, "Popen", fake_popen_class(captured, pid=4325)
    )
    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda *a: str(tmp_path)
    )

    output_path = tmp_path / "check.txt"
    assert (
        checks_module._start_background_check(  # noqa: SLF001
            "echo hi", str(output_path), str(tmp_path)
        )
        is True
    )
    assert captured["popen_argv"] == captured["detach_argv"]
    popen_kwargs = captured["popen_kwargs"]
    assert isinstance(popen_kwargs, dict)
    assert popen_kwargs["start_new_session"] is True

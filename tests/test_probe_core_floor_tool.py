from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "probe_core_floor"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("probe_core_floor_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "probe_core_floor_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def _write_pyproject(root: Path, dependency: str) -> Path:
    path = root / "pyproject.toml"
    path.write_text(
        f"""
[project]
dependencies = [
    "{dependency}",
]
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _write_src(root: Path) -> Path:
    src = root / "src"
    src.mkdir()
    (src / "facade.py").write_text(
        """
def require_rust_binding(name):
    return name


parse = require_rust_binding("parse_merge_summary")
""".lstrip(),
        encoding="utf-8",
    )
    return src


def _namespace(
    *,
    pyproject: Path,
    src: Path,
    core_dir: Path,
    cache_file: Path,
) -> argparse.Namespace:
    return argparse.Namespace(
        pyproject=pyproject,
        src=src,
        sase_core_dir=core_dir,
        cache_file=cache_file,
    )


def test_declared_floor_tracks_inclusive_minimum(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        "sase-core-rs>=0.21.3,<0.22.0",
    )

    assert tool._declared_floor(pyproject) == "0.21.3"


def test_advisory_forces_non_ok_exit_to_zero(tool: ModuleType) -> None:
    verdict = tool.Verdict(
        status="blocked_unpublished",
        exit_code=tool.EXIT_BLOCKED_UNPUBLISHED,
        floor="0.21.3",
        cache_hit=False,
        message="missing parse_merge_summary",
    )

    advisory = verdict.advisory()

    assert advisory.exit_code == 0
    assert advisory.status == "blocked_unpublished"


def test_cli_advisory_preserves_directional_json_exit_code(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verdict = tool.Verdict(
        status="blocked_unpublished",
        exit_code=tool.EXIT_BLOCKED_UNPUBLISHED,
        floor="0.21.3",
        cache_hit=True,
        message="missing parse_merge_summary",
    )
    monkeypatch.setattr(tool, "_evaluate", lambda _namespace: verdict)

    assert tool.main(["--advisory"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked_unpublished"
    assert payload["exit_code"] == tool.EXIT_BLOCKED_UNPUBLISHED


def test_extract_capabilities_from_both_probe_outputs(tool: ModuleType) -> None:
    raw = tool.RawProbeResult(
        bindings=tool.CommandResult(
            returncode=1,
            stdout="",
            stderr=(
                "sase_core_rs 0.21.3 is missing 1 of 265 required binding(s):\n"
                "  parse_merge_summary\n"
            ),
        ),
        validator=tool.CommandResult(
            returncode=1,
            stdout="",
            stderr=(
                "[validate_sase_core_rs] missing required binding(s): "
                "parse_merge_summary\n"
                "[validate_sase_core_rs] vcs_log_wire_schema_version() "
                "returned stale schema: got 2, expected 3\n"
            ),
        ),
    )

    assert tool._extract_capabilities(raw) == (
        "parse_merge_summary",
        "vcs_log_wire_schema_version",
    )


def test_blocked_unpublished_verdict_uses_cached_probe_and_core_history(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.21.3,<0.22.0")
    src = _write_src(tmp_path)
    core = tmp_path / "sase-core"
    (core / "Cargo.toml").parent.mkdir(parents=True)
    (core / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    raw = tool.RawProbeResult(
        bindings=tool.CommandResult(
            returncode=1,
            stdout="",
            stderr=(
                "sase_core_rs 0.21.3 is missing 1 of 1 required binding(s):\n"
                "  parse_merge_summary\n"
            ),
        ),
        validator=tool.CommandResult(returncode=0, stdout="", stderr=""),
    )
    cache_file = tmp_path / "cache.json"
    names = tool._collect_binding_names(src)
    key = tool._fingerprint(floor="0.21.3", binding_names=names)
    tool._write_cache(cache_file, {key: raw.to_json()})

    def _fake_git(core_dir: Path, args: list[str]) -> str:
        assert core_dir == core
        if args[:3] == ["log", "--format=%H%x00%s", "--reverse"]:
            return (
                "459bbc68f3393739969d83a729eaeadb5b32fc6a\0"
                "feat(vcs-log): add parent ids and merge summaries\n"
            )
        if args[:2] == ["tag", "--contains"]:
            return ""
        raise AssertionError(args)

    def _must_not_probe(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("cache hit should not create a scratch probe")

    monkeypatch.setattr(tool, "_git_output", _fake_git)
    monkeypatch.setattr(tool, "_run_floor_probe", _must_not_probe)

    verdict = tool._evaluate(
        _namespace(
            pyproject=pyproject,
            src=src,
            core_dir=core,
            cache_file=cache_file,
        )
    )

    assert verdict.status == "blocked_unpublished"
    assert verdict.exit_code == tool.EXIT_BLOCKED_UNPUBLISHED
    assert verdict.cache_hit is True
    assert verdict.capabilities[0].name == "parse_merge_summary"
    assert verdict.capabilities[0].commit == "459bbc6"
    assert verdict.capabilities[0].release is None


def test_stale_actionable_verdict_names_release(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.21.3,<0.22.0")
    src = _write_src(tmp_path)
    core = tmp_path / "sase-core"
    core.mkdir()
    (core / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    raw = tool.RawProbeResult(
        bindings=tool.CommandResult(
            returncode=1,
            stdout="",
            stderr=(
                "sase_core_rs 0.21.3 is missing 1 of 1 required binding(s):\n"
                "  parse_merge_summary\n"
            ),
        ),
        validator=tool.CommandResult(returncode=0, stdout="", stderr=""),
    )
    cache_file = tmp_path / "cache.json"
    names = tool._collect_binding_names(src)
    key = tool._fingerprint(floor="0.21.3", binding_names=names)
    tool._write_cache(cache_file, {key: raw.to_json()})

    def _fake_git(_core_dir: Path, args: list[str]) -> str:
        if args[:3] == ["log", "--format=%H%x00%s", "--reverse"]:
            return (
                "459bbc68f3393739969d83a729eaeadb5b32fc6a\0"
                "feat(vcs-log): add parent ids and merge summaries\n"
            )
        if args[:2] == ["tag", "--contains"]:
            return "v0.22.0\n"
        raise AssertionError(args)

    monkeypatch.setattr(tool, "_git_output", _fake_git)

    verdict = tool._evaluate(
        _namespace(
            pyproject=pyproject,
            src=src,
            core_dir=core,
            cache_file=cache_file,
        )
    )

    assert verdict.status == "stale_actionable"
    assert verdict.exit_code == tool.EXIT_STALE_ACTIONABLE
    assert verdict.capabilities[0].release == "v0.22.0"

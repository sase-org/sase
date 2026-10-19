"""Step-runner and verdict-merge tests for the exercise_release tool."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "exercise_release"


def load_tool() -> ModuleType:
    loader = SourceFileLoader("exercise_release_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "exercise_release_tool",
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
    return load_tool()


CORE_VERSION = "0.42.0"
CANDIDATE_VERSION = "0.18.0"


class FakeRunner:
    """Scripted stand-in for the tool's Runner."""

    sase_init: Path = Path("/nonexistent/__init__.py")

    def __init__(self, tool: ModuleType) -> None:
        self._tool = tool
        self.calls: list[list[str]] = []
        self.version_stdout = ""
        self.list_entries: list[dict[str, Any]] = []

    def run(
        self,
        argv: Any,
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int = 300,
    ) -> Any:
        words = list(argv)
        self.calls.append(words)
        ok = self._tool.Completed(args=words, returncode=0, stdout="", stderr="")
        tail = words[1:]
        if tail[:2] == ["tool", "install"]:
            return ok
        if tail[:1] == ["-c"] and "import sase.main.entry" in tail[1]:
            return self._tool.Completed(
                args=words,
                returncode=0,
                stdout=str(self.sase_init) + "\n",
                stderr="",
            )
        if tail == ["version", "-j"]:
            return self._tool.Completed(
                args=words, returncode=0, stdout=self.version_stdout, stderr=""
            )
        if len(tail) == 2 and tail[0] == "run":
            return self._tool.Completed(
                args=words, returncode=0, stdout="Agent started (PID 4242)\n", stderr=""
            )
        if tail[:2] == ["agent", "wait"]:
            return ok
        if tail[:2] == ["agent", "list"]:
            return self._tool.Completed(
                args=words,
                returncode=0,
                stdout=json.dumps(self.list_entries),
                stderr="",
            )
        if tail[:1] == ["screenshot"]:
            out_index = words.index("-o") + 1
            Path(words[out_index]).write_bytes(b"x" * 11_000)
            return ok
        if tail[:2] == ["pip", "check"]:
            return ok
        if tail == ["core", "health", "--json"]:
            return self._tool.Completed(
                args=words,
                returncode=0,
                stdout=json.dumps({"probe_ok": True, "error": None}),
                stderr="",
            )
        raise AssertionError(f"unexpected argv: {words}")


def _version_payload(core_version: str = CORE_VERSION) -> str:
    return json.dumps(
        {
            "packages": [
                {"name": "sase", "role": "host", "distribution_version": "0.18.0"},
                {
                    "name": "sase-core-rs",
                    "role": "core",
                    "distribution_version": core_version,
                },
            ]
        }
    )


def _write_run_record(run_dir: Path, marker: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "submitted_prompt.md").write_text(marker + "\n", encoding="utf-8")
    (run_dir / "agent_meta.json").write_text(
        json.dumps({"llm_provider": "fakey", "model": "fakey-large"}), encoding="utf-8"
    )
    (run_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "exec_llm_provider": "fakey"}),
        encoding="utf-8",
    )
    (run_dir / "invocation-1.json").write_text("{}", encoding="utf-8")


def _isolate_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: ModuleType
) -> Path:
    home = tmp_path / "home"
    (tmp_path / "tool-bin").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "tool-dir"))
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "tool-bin"))
    monkeypatch.setenv("SASE_AGENT_NAME", "session-leak")
    monkeypatch.setattr(
        tool.shutil,
        "which",
        lambda command, *args, **kwargs: (
            "/usr/bin/tmux" if command == "tmux" else "/usr/bin/uv"
        ),
    )
    return home


def _leg_config(tool: ModuleType, tmp_path: Path, **overrides: Any) -> Any:
    dist = tmp_path / "sase-0.18.0-py3-none-any.whl"
    dist.write_bytes(b"wheel-bytes")
    kwargs: dict[str, Any] = {
        "os_name": "ubuntu-latest",
        "artifact": "wheel",
        "dist_path": dist,
        "candidate_version": CANDIDATE_VERSION,
        "core_version": CORE_VERSION,
        "run_id": "7",
        "attempt": "1",
        "previous_version": "0.17.0",
        "apply_probe": "none",
        "work_dir": tmp_path / "work",
        "out_path": tmp_path / "leg.json",
        "candidate_id": "candidate-abc",
        "generation": 1,
    }
    kwargs.update(overrides)
    return tool.LegConfig(**kwargs)


def _prepare_green(
    tool: ModuleType,
    runner: FakeRunner,
    home: Path,
    marker: str,
    upgrade_marker: str | None = None,
) -> None:
    run_dir = home / "projects" / "home" / "artifacts" / "run-1"
    _write_run_record(run_dir, marker)
    entries = [{"artifacts_dir": str(run_dir), "status": "DONE"}]
    if upgrade_marker is not None:
        upgrade_dir = home / "projects" / "home" / "artifacts" / "run-2"
        _write_run_record(upgrade_dir, upgrade_marker)
        entries.append({"artifacts_dir": str(upgrade_dir), "status": "DONE"})
    runner.list_entries = entries
    runner.version_stdout = _version_payload()


def test_full_wheel_leg_is_green(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolate_env(monkeypatch, tmp_path, tool)
    runner = FakeRunner(tool)
    (tmp_path / "tool-bin" / "sase").write_bytes(b"exe")
    marker = "exercise-linux-wheel-7-1"
    _prepare_green(tool, runner, home, marker, upgrade_marker="upgrade-linux-7-1")
    leg = tool.run_leg(_leg_config(tool, tmp_path), runner)
    assert leg["verdict"] == "pass"
    assert leg["failing_step"] is None
    assert [s["name"] for s in leg["steps"]] == list(tool.STEP_NAMES)
    assert all(s["ok"] for s in leg["steps"])


def test_sdist_leg_skips_upgrade(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolate_env(monkeypatch, tmp_path, tool)
    runner = FakeRunner(tool)
    (tmp_path / "tool-bin" / "sase").write_bytes(b"exe")
    _prepare_green(tool, runner, home, "exercise-linux-sdist-7-1")
    config = _leg_config(tool, tmp_path, artifact="sdist", previous_version="")
    leg = tool.run_leg(config, runner)
    assert leg["verdict"] == "pass"
    upgrade = next(s for s in leg["steps"] if s["name"] == "upgrade-nminus1")
    assert upgrade["ok"] is True


def test_first_failure_stops_the_leg(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolate_env(monkeypatch, tmp_path, tool)
    runner = FakeRunner(tool)
    (tmp_path / "tool-bin" / "sase").write_bytes(b"exe")

    calls = runner.run

    def failing_install(
        argv: Any, *, env: Any = None, cwd: Any = None, timeout: int = 300
    ) -> Any:
        if "tool install" in " ".join(argv):
            return tool.Completed(
                args=list(argv), returncode=1, stdout="", stderr="boom"
            )
        return calls(argv, env=env, cwd=cwd, timeout=timeout)

    runner.run = failing_install  # type: ignore[method-assign]
    leg = tool.run_leg(_leg_config(tool, tmp_path), runner)
    assert leg["verdict"] == "fail"
    assert leg["failing_step"] == "install"
    assert "boom" in (leg["reason"] or "")
    ran = [s["name"] for s in leg["steps"] if not s["skipped"]]
    assert ran == ["install"]
    assert home.is_dir()


def test_core_pin_mismatch_is_red(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolate_env(monkeypatch, tmp_path, tool)
    runner = FakeRunner(tool)
    (tmp_path / "tool-bin" / "sase").write_bytes(b"exe")
    _prepare_green(tool, runner, home, "exercise-linux-wheel-7-1")
    runner.version_stdout = _version_payload(core_version="0.41.0")
    leg = tool.run_leg(_leg_config(tool, tmp_path), runner)
    assert leg["verdict"] == "fail"
    assert leg["failing_step"] == "core-pin"
    assert "0.41.0" in (leg["reason"] or "")


def test_probe_deletes_the_module_on_macos_only(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for os_name, deleted in (("macos-latest", True), ("ubuntu-latest", False)):
        home = _isolate_env(monkeypatch, tmp_path / os_name.replace("-", "_"), tool)
        runner = FakeRunner(tool)
        pkg = tmp_path / os_name.replace("-", "_") / "pkg"
        pkg.mkdir(parents=True, exist_ok=True)
        init = pkg / "__init__.py"
        init.write_text("# probe target\n", encoding="utf-8")
        runner.sase_init = pkg / "entry.py"
        runner.sase_init.write_text("# probe target\n", encoding="utf-8")
        runner.version_stdout = _version_payload()
        config = _leg_config(
            tool,
            tmp_path / os_name.replace("-", "_"),
            os_name=os_name,
            apply_probe="break-macos",
        )
        ctx = tool.LegContext(
            config=config,
            runner=runner,
            env=tool.build_leg_env(dict(os.environ)),
            sase_home=home,
            tool_bin=tmp_path / "tool-bin",
            tool_python=tmp_path / "tool-bin" / "python",
            exe=tmp_path / "tool-bin" / "sase",
        )
        (tmp_path / "tool-bin").mkdir(parents=True, exist_ok=True)
        (tmp_path / "tool-bin" / "sase").write_bytes(b"exe")
        step = tool.step_install(ctx)
        assert step.ok is True
        assert init.exists()
        assert runner.sase_init.exists() is not deleted
        assert ("probe break-macos" in step.detail) is deleted


def test_await_done_times_out_when_missing(tool: ModuleType, tmp_path: Path) -> None:
    assert tool._await_done(tmp_path / "norun", timeout_s=0) is False


def test_session_env_is_scrubbed(tool: ModuleType) -> None:
    env = {
        "PATH": "/usr/bin",
        "HOME": "/tmp/ex-home",
        "SASE_HOME": "/tmp/ex-home",
        "SASE_AGENT_NAME": "sase-9x9.9",
        "SASE_AGENT_WORKSPACE_NUM": "17",
        "SASE_ARTIFACTS_DIR": "/tmp/ex-home/projects/exercise/artifacts",
    }
    scrubbed = tool.scrub_session_env(env)
    assert scrubbed["SASE_HOME"] == "/tmp/ex-home"
    assert scrubbed["SASE_ARTIFACTS_DIR"].endswith("artifacts")
    assert "SASE_AGENT_NAME" not in scrubbed
    assert "SASE_AGENT_WORKSPACE_NUM" not in scrubbed


def test_owner_identity_is_seeded(tool: ModuleType, tmp_path: Path) -> None:
    home = tmp_path / "home"
    tool.seed_owner_identity(home, tmp_path / "config")
    assert (home / "machine_name").read_text(encoding="utf-8").strip() == (
        tool.SEED_MACHINE_NAME
    )
    overlay = tmp_path / "config" / "sase" / "sase_exercise.yml"
    assert tool.SEED_USERNAME in overlay.read_text(encoding="utf-8")


def _pass_leg(os_name: str, artifact: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "os": os_name,
        "artifact": artifact,
        "candidate_id": "candidate-abc",
        "generation": 1,
        "run_id": 1,
        "attempt": 1,
        "core_version": CORE_VERSION,
        "verdict": "pass",
        "failing_step": None,
        "reason": None,
        "steps": [],
    }


def _write_legs(tmp_path: Path, legs: dict[str, dict[str, Any]]) -> list[Path]:
    paths = []
    for name, leg in legs.items():
        path = tmp_path / name
        path.write_text(json.dumps(leg), encoding="utf-8")
        paths.append(path)
    return paths


def test_merge_all_green(tool: ModuleType, tmp_path: Path) -> None:
    legs = {
        f"exercise-{os_name}-{artifact}.json": _pass_leg(os_name, artifact)
        for os_name, artifact in tool.EXPECTED_LEGS
    }
    merged = tool.merge_legs(
        _write_legs(tmp_path, legs),
        candidate_id="candidate-abc",
        generation=1,
        run_id=1,
        attempt=1,
    )
    assert merged["verdict"] == "pass"
    assert merged["reason"] == "4/4 legs green for candidate-abc"


def test_merge_probe_case_reports_exercise_red_macos(
    tool: ModuleType, tmp_path: Path
) -> None:
    legs = {
        f"exercise-{os_name}-{artifact}.json": _pass_leg(os_name, artifact)
        for os_name, artifact in tool.EXPECTED_LEGS
    }
    for artifact in ("wheel", "sdist"):
        name = f"exercise-macos-latest-{artifact}.json"
        legs[name] = {
            **legs[name],
            "verdict": "fail",
            "failing_step": "core-pin",
            "reason": "installed core missing",
        }
    merged = tool.merge_legs(
        _write_legs(tmp_path, legs),
        candidate_id="candidate-abc",
        generation=1,
        run_id=1,
        attempt=1,
    )
    assert merged["verdict"] == "fail"
    assert merged["reason"].startswith("EXERCISE_RED(macos)")


def test_merge_missing_leg_is_red(tool: ModuleType, tmp_path: Path) -> None:
    legs = {
        f"exercise-{os_name}-{artifact}.json": _pass_leg(os_name, artifact)
        for os_name, artifact in tool.EXPECTED_LEGS
        if (os_name, artifact) != ("macos-latest", "sdist")
    }
    merged = tool.merge_legs(
        _write_legs(tmp_path, legs),
        candidate_id="candidate-abc",
        generation=1,
        run_id=1,
        attempt=1,
    )
    assert merged["verdict"] == "fail"
    assert merged["reason"].startswith("EXERCISE_RED(macos)")
    assert "macos-sdist evidence missing" in merged["reason"]


def test_merge_linux_failure_names_linux(tool: ModuleType, tmp_path: Path) -> None:
    legs = {
        f"exercise-{os_name}-{artifact}.json": _pass_leg(os_name, artifact)
        for os_name, artifact in tool.EXPECTED_LEGS
    }
    name = "exercise-ubuntu-latest-wheel.json"
    legs[name] = {
        **legs[name],
        "verdict": "fail",
        "failing_step": "health",
        "reason": "core probe red",
    }
    merged = tool.merge_legs(
        _write_legs(tmp_path, legs),
        candidate_id="candidate-abc",
        generation=1,
        run_id=1,
        attempt=1,
    )
    assert merged["verdict"] == "fail"
    assert merged["reason"].startswith("EXERCISE_RED(linux)")


def test_merge_unreadable_leg_is_red(tool: ModuleType, tmp_path: Path) -> None:
    legs = {
        f"exercise-{os_name}-{artifact}.json": _pass_leg(os_name, artifact)
        for os_name, artifact in tool.EXPECTED_LEGS
    }
    bad = tmp_path / "exercise-ubuntu-latest-wheel.json"
    bad.write_text("{not json", encoding="utf-8")
    paths = [bad] + [
        tmp_path / name for name in legs if name != "exercise-ubuntu-latest-wheel.json"
    ]
    for name, leg in legs.items():
        if name != "exercise-ubuntu-latest-wheel.json":
            (tmp_path / name).write_text(json.dumps(leg), encoding="utf-8")
    merged = tool.merge_legs(
        paths, candidate_id="candidate-abc", generation=1, run_id=1, attempt=1
    )
    assert merged["verdict"] == "fail"
    assert merged["reason"].startswith("EXERCISE_RED(linux)")

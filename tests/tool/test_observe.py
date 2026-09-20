from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_show
from sase.tool.argv import ResolvedToolArgv, resolve_run_argv
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.observe import fingerprints_mutated, observe_fingerprint
from sase.tool.query import ToolShowCliRequest, handle_show
from sase.tool.sample import SAMPLE_INTERVAL_SECONDS, LoadSampler


def _git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.example"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


def _home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, project: str = "demo"
) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("SASE_PROJECT", project)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ID", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("SASE_PROC_ID", raising=False)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _resolved(argv: list[str] | None = None) -> ResolvedToolArgv:
    command = tuple(argv or ["true"])
    return ResolvedToolArgv(
        tool_name=None,
        argv=command,
        extra_args=(),
        display_argv=command,
        private_argv=None,
        definition={
            "schema_version": 1,
            "name": "ad-hoc",
            "argv": list(command),
            "description": "",
            "stages": "none",
            "inputs": [],
            "env": [],
            "args": "allow",
            "fingerprint": {"repos": [], "toolchain": {}},
        },
        digest=None,
        cwd=None,
        adhoc=True,
    )


def _run(*argv: str) -> int:
    return execute_tool_run(
        ToolRunCliRequest(quiet=False, verbose=False, tail_lines=200, words=argv)
    )


def test_non_git_cwd_is_explicitly_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    fingerprint = observe_fingerprint(_resolved())
    assert fingerprint["completeness"]["complete"] is False
    assert any("non-Git" in item for item in fingerprint["completeness"]["missing"])
    assert fingerprint["repos"][0].get("head") is None


def test_clean_and_dirty_git_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _git_init(tmp_path / "repo")
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    clean = observe_fingerprint(_resolved())
    assert clean["completeness"]["complete"] is True
    assert clean["repos"][0]["dirty_paths"] == []
    assert clean["repos"][0]["head"]
    assert "/" not in (clean["repos"][0]["dirty_paths"] or [{}])[0].get("path", "ok")

    (repo / "unstaged.txt").write_text("u\n", encoding="utf-8")
    untracked = observe_fingerprint(_resolved())
    paths = {item["path"]: item for item in untracked["repos"][0]["dirty_paths"]}
    assert paths["unstaged.txt"]["status"] == "untracked"

    subprocess.run(["git", "add", "unstaged.txt"], cwd=repo, check=True)
    staged = observe_fingerprint(_resolved())
    staged_paths = {item["path"]: item for item in staged["repos"][0]["dirty_paths"]}
    assert staged_paths["unstaged.txt"]["status"] == "added"

    (repo / "unstaged.txt").write_text("edited\n", encoding="utf-8")
    mixed = observe_fingerprint(_resolved())
    mixed_paths = {item["path"]: item for item in mixed["repos"][0]["dirty_paths"]}
    assert mixed_paths["unstaged.txt"]["status"] == "modified"

    subprocess.run(["git", "add", "unstaged.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "track"], cwd=repo, check=True)
    (repo / "unstaged.txt").unlink()
    deleted = observe_fingerprint(_resolved())
    deleted_paths = {item["path"]: item for item in deleted["repos"][0]["dirty_paths"]}
    assert deleted_paths["unstaged.txt"]["status"] == "deleted"
    assert deleted_paths["unstaged.txt"]["kind"] == "deleted"


def test_executable_mode_change_is_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _git_init(tmp_path / "repo")
    script = repo / "tool.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "tool.sh"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "script"], cwd=repo, check=True)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    fingerprint = observe_fingerprint(_resolved())
    paths = {item["path"]: item for item in fingerprint["repos"][0]["dirty_paths"]}
    assert "tool.sh" in paths
    assert paths["tool.sh"]["mode"] is not None
    assert int(paths["tool.sh"]["mode"], 8) & 0o111


def test_identical_contents_in_two_checkout_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    left = _git_init(tmp_path / "left")
    (left / "note.txt").write_text("same\n", encoding="utf-8")
    right = tmp_path / "right"
    shutil.copytree(left, right)
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(left)
    first = observe_fingerprint(_resolved())
    monkeypatch.chdir(right)
    second = observe_fingerprint(_resolved())
    assert first["repos"][0]["identity"] == second["repos"][0]["identity"]
    assert first["repos"][0]["head"] == second["repos"][0]["head"]
    left_hashes = {
        item["path"]: item.get("content_hash")
        for item in first["repos"][0]["dirty_paths"]
    }
    right_hashes = {
        item["path"]: item.get("content_hash")
        for item in second["repos"][0]["dirty_paths"]
    }
    assert left_hashes == right_hashes
    dumped = yaml.safe_dump(first)
    assert str(left) not in dumped
    assert str(right) not in dumped


def test_named_tool_input_mutation_sets_mutated_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _git_init(tmp_path / "proj")
    (root / "sase").mkdir()
    (root / "keep.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "keep.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "keep"], cwd=root, check=True)
    (root / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "mutate": {
                        "argv": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; Path('keep.txt').write_text('after\\n')",
                        ],
                        "description": "mutate",
                        "inputs": ["keep.txt"],
                        "args": "deny",
                        "fingerprint": {"repos": [], "toolchain": {}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(root)
    clear_config_cache()
    code = _run("mutate")
    assert code == 0
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    recorded = tool_run_show(run["run_id"])["run"]
    assert recorded["mutated_input"] is True
    assert fingerprints_mutated(
        recorded["fingerprint_before"], recorded["fingerprint_after"]
    )


def test_missing_input_is_explicitly_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _git_init(tmp_path / "proj")
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "need": {
                        "argv": ["true"],
                        "inputs": ["missing-input.txt"],
                        "fingerprint": {"repos": [], "toolchain": {}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(root)
    clear_config_cache()
    fingerprint = observe_fingerprint(resolve_run_argv(["need"]))
    assert fingerprint["completeness"]["complete"] is False
    assert any(
        "missing input" in item for item in fingerprint["completeness"]["missing"]
    )
    assert fingerprints_mutated(fingerprint, fingerprint) is None


def test_failing_probe_is_incomplete_evidence_not_a_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _git_init(tmp_path / "proj")
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "probe": {
                        "argv": ["true"],
                        "description": "probe",
                        "fingerprint": {
                            "toolchain": {
                                "good": [sys.executable, "--version"],
                                "broken": [
                                    sys.executable,
                                    "-c",
                                    "import sys; print('Traceback: no module'); sys.exit(1)",
                                ],
                            },
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(root)
    clear_config_cache()
    fingerprint = observe_fingerprint(resolve_run_argv(["probe"]))
    toolchain = fingerprint["toolchain"]
    assert "incomplete" not in toolchain["good"]
    assert toolchain["broken"]["exit_code"] == 1
    assert toolchain["broken"]["incomplete"] == "toolchain probe broken exited 1"
    assert fingerprint["completeness"]["complete"] is False
    assert "toolchain probe broken exited 1" in fingerprint["completeness"]["missing"]


def test_probe_timeout_is_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _git_init(tmp_path / "proj")
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "probe": {
                        "argv": ["true"],
                        "description": "probe",
                        "fingerprint": {
                            "toolchain": {"hang": ["sleep", "30"]},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(root)
    clear_config_cache()
    resolved = resolve_run_argv(["probe"])
    started = time.monotonic()
    fingerprint = observe_fingerprint(resolved)
    elapsed = time.monotonic() - started
    assert elapsed < 5
    probe = fingerprint["toolchain"]["hang"]
    assert probe.get("incomplete") == "probe timeout"
    assert fingerprint["completeness"]["complete"] is False


def test_linked_repo_change_sets_mutated_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _git_init(tmp_path / "proj")
    other = _git_init(tmp_path / "other")
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "repos": {"linked": [{"name": "other", "path": str(other)}]},
                "tools": {
                    "touch-other": {
                        "argv": [
                            sys.executable,
                            "-c",
                            f"from pathlib import Path; Path({str(other / 'extra.txt')!r}).write_text('x\\n')",
                        ],
                        "description": "linked",
                        "fingerprint": {"repos": ["other"]},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(root)
    clear_config_cache()
    assert _run("touch-other") == 0
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    shown = tool_run_show(run["run_id"])["run"]
    assert shown["mutated_input"] is True
    identities = [repo["identity"] for repo in shown["fingerprint_after"]["repos"]]
    assert identities == ["other"]


def test_missing_linked_repo_is_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _git_init(tmp_path / "proj")
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "ping": {
                        "argv": ["true"],
                        "fingerprint": {"repos": ["absent-repo"]},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(root)
    clear_config_cache()
    fingerprint = observe_fingerprint(resolve_run_argv(["ping"]))
    assert fingerprint["completeness"]["complete"] is False
    assert any(
        "missing repo" in item for item in fingerprint["completeness"]["missing"]
    )


def test_unavailable_psi_is_null_not_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool import sample as sample_mod

    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(sample_mod, "_read_psi", lambda: None)
    payload = sample_mod._collect_load_sample(run_id="r1", elapsed_ms=0)
    assert payload["psi_cpu_some"] is None
    assert payload["psi_memory_some"] is None
    assert payload["psi_io_some"] is None
    assert "PSI unavailable on this host" in payload["availability"]
    assert 0 not in (
        payload["psi_cpu_some"],
        payload["psi_memory_some"],
        payload["psi_io_some"],
    )


def test_sampler_start_periodic_and_finish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    recorded: list[dict[str, object]] = []

    def fake_append(sample: dict[str, object]) -> bool:
        recorded.append(sample)
        return True

    monkeypatch.setattr("sase.tool.sample._append_load_sample", fake_append)
    sampler = LoadSampler(run_id="r1", started=time.monotonic(), interval=0.2)
    sampler.maybe_sample(force=True)
    time.sleep(0.25)  # sase-test-wait: periodic sample interval
    sampler.maybe_sample()
    time.sleep(0.25)  # sase-test-wait: final sample interval
    sampler.maybe_sample(force=True)
    sampler.stop()
    sampler.maybe_sample(force=True)
    assert len(recorded) >= 3
    elapsed = [int(sample["elapsed_ms"]) for sample in recorded]
    assert elapsed[0] <= elapsed[-1]


def test_executor_records_samples_and_show_lists_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FastSampler(LoadSampler):
        def __init__(self, *args, **kwargs):  # noqa: ANN002,ANN003
            kwargs["interval"] = 0.2
            super().__init__(*args, **kwargs)

    _home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.tool.executor.LoadSampler", FastSampler)
    code = _run("--", "sleep", "0.55")
    assert code == 0
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    shown = tool_run_show(run["run_id"])
    samples = shown.get("samples") or []
    assert len(samples) >= 3
    assert shown["run"]["fingerprint_before"] is not None
    assert shown["run"]["fingerprint_after"] is not None
    assert shown["run"]["fingerprint_before"]["completeness"]["complete"] is False
    code = handle_show(ToolShowCliRequest(run_id=run["run_id"], json=False, logs=False))
    assert code == 0


def test_concurrent_runs_keep_independent_event_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = _home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    assert _run("--", "true") == 0
    sase = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "sase"
    env = os.environ.copy()
    env["SASE_HOME"] = str(home)
    for key in (
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
    ):
        env.pop(key, None)
    children = [
        subprocess.Popen(
            [str(sase), "tool", "run", "--", "sh", "-c", f"printf {tag}; sleep 0.2"],
            env=env,
            cwd=str(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for tag in ("a", "b")
    ]
    codes = [proc.wait(timeout=20) for proc in children]
    assert codes == [0, 0]
    listed = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    recorded = [run for run in listed if (run.get("logs") or {}).get("events_path")]
    assert len(recorded) >= 2
    event_paths = {(run.get("logs") or {}).get("events_path") for run in recorded}
    assert len(event_paths) == len(recorded)


def test_sample_interval_default_is_ten_seconds() -> None:
    assert SAMPLE_INTERVAL_SECONDS == 10.0

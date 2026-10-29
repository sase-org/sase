"""Subprocess tests for the after-rebase gate runner.

The Rust policy matrix itself is covered by sase-core tests; these tests
prove the runner's job: project-scoped configuration, bounded process
execution with group teardown, capped evidence, fail-open errors, and exact
delegation of command facts plus the checker's report to the facade.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.workflows.commit import rebase_gate_runner as runner

HEAD = "a" * 40
TREE = "b" * 40
FINDING_PATH = "src/sase/example.py"


def make_context(**overrides: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "schema_version": 1,
        "repository_root": "/repo",
        "inputs": [
            {
                "old_head": "1" * 40,
                "upstream_tip": "2" * 40,
                "merge_base": "3" * 40,
            }
        ],
        "current_head": HEAD,
        "current_tree": TREE,
        "changed_paths": [{"path": FINDING_PATH, "kind": "modified"}],
    }
    context.update(overrides)
    return context


def make_report(status: str, **overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "checked_head": HEAD,
        "checked_tree": TREE,
        "status": status,
        "findings": [],
    }
    if status == "findings":
        report["findings"] = [
            {
                "path": FINDING_PATH,
                "line": 3,
                "module": "sase.example",
                "imported_name": "thing",
                "explanation": "renamed upstream",
            }
        ]
    report.update(overrides)
    return report


def write_checker(
    path: Path,
    *,
    exit_code: int,
    report: dict[str, Any] | None = None,
    raw_body: str | None = None,
    preamble: str = "",
) -> str:
    """Write a checker script; return a shell command running it."""
    lines = ["import json, os, sys"]
    if preamble:
        lines.append(preamble)
    lines.extend(
        [
            "ctx_path = os.environ.get('SASE_REBASE_CONTEXT', '')",
            "res_path = os.environ.get('SASE_REBASE_RESULT', '')",
            "assert ctx_path and res_path, 'gate env vars missing'",
            "ctx = json.load(open(ctx_path))",
            f"assert ctx['current_head'] == {HEAD!r}, ctx",
        ]
    )
    if raw_body is not None:
        lines.append(f"open(res_path, 'w').write({raw_body!r})")
    elif report is not None:
        lines.append(f"open(res_path, 'w').write({json.dumps(report)!r})")
    lines.append(f"sys.exit({exit_code})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"{sys.executable} {path}"


class GateHarness:
    """Patch config loading and the facade; capture delegation."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.captured: dict[str, Any] = {}
        self.configs: dict[str, dict[str, Any]] = {}
        self.loaded_for: list[str] = []
        self.monkeypatch = monkeypatch
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

        def fake_load(local_path: Path) -> dict[str, Any]:
            self.loaded_for.append(str(local_path))
            return self.configs.get(
                str(local_path),
                {"commit_hooks": {"after_rebase": ""}},
            )

        monkeypatch.setattr(runner, "load_merged_config_for_local_path", fake_load)

    def configure(
        self,
        root: Path,
        hook: Any,
        timeout: Any = 5.0,
    ) -> None:
        self.configs[os.path.abspath(str(root))] = {
            "commit_hooks": {
                "after_rebase": hook,
                "after_rebase_timeout_seconds": timeout,
            }
        }

    def fake_classify(self, verdict: str, **overrides: Any) -> None:
        def classify(
            context: Any,
            config: Any,
            command: Any,
            report: Any,
        ) -> dict[str, Any]:
            self.captured.update(
                context=context, config=config, command=command, report=report
            )
            decision: dict[str, Any] = {
                "schema_version": 1,
                "verdict": verdict,
                "reason": f"test {verdict}",
                "findings": [],
                "diagnostics": None,
            }
            decision.update(overrides)
            return decision  # type: ignore[return-value]

        self.monkeypatch.setattr(
            "sase.core.rebase_gate.classify_rebase_gate_result", classify
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> GateHarness:
    return GateHarness(monkeypatch, tmp_path)


def test_clean_report_permits_push_and_delegates_exact_facts(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(
        tmp_path / "clean.py", exit_code=0, report=make_report("clean")
    )
    harness.configure(root, hook)
    harness.fake_classify("pass")

    seen: dict[str, Any] = {}
    real_popen = subprocess.Popen

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return real_popen(*args, **kwargs)

    harness.monkeypatch.setattr(subprocess, "Popen", spy)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "pass"
    # The hook runs verbatim: changed paths travel in the JSON file, never
    # interpolated into shell text.
    assert seen["args"] == (hook,)
    env = seen["kwargs"]["env"]
    assert env[runner.REBASE_GATE_CONTEXT_ENV].endswith("context.json")
    assert env[runner.REBASE_GATE_RESULT_ENV].endswith("result.json")
    assert seen["kwargs"]["cwd"] == os.path.abspath(str(root))
    assert harness.captured["command"] == {
        "timed_out": False,
        "exit_code": 0,
    }
    assert harness.captured["config"] == {
        "hook_command": hook,
        "timeout_seconds": 5.0,
    }
    assert harness.captured["report"]["status"] == "clean"
    assert harness.captured["report"]["findings"] == []
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["verdict"] == "pass"
    assert metadata["changed_path_count"] == 1
    assert metadata["current_head"] == HEAD
    assert metadata["duration_seconds"] >= 0


def test_findings_report_blocks_push(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("findings")
    hook = write_checker(tmp_path / "checker.py", exit_code=1, report=report)
    harness.configure(root, hook)
    harness.fake_classify("block", findings=report["findings"])

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "block"
    assert harness.captured["command"] == {
        "timed_out": False,
        "exit_code": 1,
    }
    assert harness.captured["report"]["findings"][0]["imported_name"] == "thing"


def test_error_report_warns_and_allows_push(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("error")
    report["diagnostics"] = "cannot import third-party dep"
    hook = write_checker(tmp_path / "checker.py", exit_code=1, report=report)
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"]["status"] == "error"


@pytest.mark.parametrize("hook", ["false", "definitely-missing-sase-gate-bin"])
def test_crash_without_report_warns(
    harness: GateHarness, tmp_path: Path, hook: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"] is None
    assert harness.captured["command"]["timed_out"] is False
    assert harness.captured["command"]["exit_code"] != 0


def test_stale_report_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("findings", checked_head="0" * 40)
    hook = write_checker(tmp_path / "checker.py", exit_code=1, report=report)
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"]["checked_head"] == "0" * 40


def test_unsupported_exit_status_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("findings")
    hook = write_checker(tmp_path / "checker.py", exit_code=2, report=report)
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["command"]["exit_code"] == 2


def test_malformed_report_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(tmp_path / "checker.py", exit_code=0, raw_body="{not json")
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"] is None


def test_oversize_report_is_dropped(
    harness: GateHarness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(runner, "_RESULT_CAP_BYTES", 64)
    hook = write_checker(
        tmp_path / "checker.py",
        exit_code=0,
        report=make_report("clean"),
    )
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"] is None


def test_signalled_hook_reports_signal(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "kill -TERM $$")
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["command"]["timed_out"] is False
    assert harness.captured["command"]["signal"] == 15
    assert "exit_code" not in harness.captured["command"]


def test_spawn_failure_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "true")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no fork for you")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert "no fork" in (harness.captured["command"]["spawn_error"] or "")


def test_timeout_kills_process_group_and_warns(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    # A background child inherits stdout; the group kill must still reap
    # promptly instead of hanging on the open pipe.
    harness.configure(root, "sleep 30 & exec sleep 30", timeout=0.5)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["command"]["timed_out"] is True
    assert outcome.duration_seconds < 8.0
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "decided"
    assert metadata["timed_out"] is True


def test_excessive_output_is_bounded(
    harness: GateHarness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.workflows.commit.hook_utils as hook_utils

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(hook_utils, "HOOK_LOG_CAP_BYTES", 1024)
    script = tmp_path / "noisy.py"
    script.write_text(
        "import os, sys\n"
        "sys.stdout.write('x' * 100000 + chr(10))\n"
        "sys.stderr.write('tail-marker' + chr(10))\n"
        "open(os.environ['SASE_REBASE_RESULT'], 'w').write"
        f"({json.dumps(json.dumps(make_report('clean')))!r})\n",
        encoding="utf-8",
    )
    harness.configure(root, f"{sys.executable} {script}")
    harness.fake_classify("pass")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "pass"
    assert "tail-marker" in outcome.stderr_tail
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["stdout_truncated"] is True
    paths = metadata["paths"]
    stdout_log = Path(str(paths["stdout"])).read_text(encoding="utf-8")
    assert "truncated after 1024 bytes" in stdout_log
    assert len(outcome.stdout_tail.encode("utf-8")) <= 16_384


def test_failed_log_creation_warns_without_launching(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    harness.monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(blocker))
    harness.configure(root, "true")
    harness.fake_classify("pass")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("gate must not launch without evidence")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert outcome.metadata_path is None


def test_cleanup_failure_keeps_decision(
    harness: GateHarness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil as shutil_module

    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(
        tmp_path / "clean.py", exit_code=0, report=make_report("clean")
    )
    harness.configure(root, hook)
    harness.fake_classify("pass")

    real_rmtree = shutil_module.rmtree
    attempted: list[str] = []

    def boom(path: Any, *args: Any, **kwargs: Any) -> Any:
        attempted.append(str(path))
        if "sase-rebase-gate-" in str(path):
            raise OSError("cannot clean")
        return real_rmtree(path, *args, **kwargs)

    harness.monkeypatch.setattr(shutil_module, "rmtree", boom)
    try:
        outcome = runner.run_after_rebase_gate(make_context(), str(root))
    finally:
        for path_text in attempted:
            if "sase-rebase-gate-" in path_text:
                real_rmtree(path_text, ignore_errors=True)

    assert outcome.decision["verdict"] == "pass"
    assert "could not remove temporary directory" in capsys.readouterr().out


def test_configuration_is_isolated_between_project_roots(
    harness: GateHarness, tmp_path: Path
) -> None:
    root_a = tmp_path / "proj-a"
    root_b = tmp_path / "proj-b"
    root_a.mkdir()
    root_b.mkdir()
    harness.configure(root_a, "true", timeout=2.0)
    harness.configure(root_b, "true", timeout=4.0)
    harness.fake_classify("pass")

    outcome_a = runner.run_after_rebase_gate(make_context(), str(root_a))
    outcome_b = runner.run_after_rebase_gate(make_context(), str(root_b))

    assert outcome_a.decision["verdict"] == "pass"
    assert outcome_b.decision["verdict"] == "pass"
    assert harness.loaded_for[-2:] == [
        os.path.abspath(str(root_a)),
        os.path.abspath(str(root_b)),
    ]
    # The second run's captured config proves per-root resolution: the
    # harness returns each root's own layer.
    assert harness.captured["config"]["timeout_seconds"] == 4.0


def test_disabled_hook_launches_no_process(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "   ")
    harness.fake_classify("skip")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("disabled gate must not launch a process")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "skip"
    assert outcome.metadata_path is None
    assert harness.captured["config"] == {
        "hook_command": "",
        "timeout_seconds": 5.0,
    }
    assert harness.captured["command"] == {}
    assert harness.captured["report"] is None


@pytest.mark.parametrize("timeout", ["ten", True, [5], {"s": 5}])
def test_invalid_timeout_warns_without_launching(
    harness: GateHarness, tmp_path: Path, timeout: Any
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "true", timeout=timeout)
    harness.fake_classify("pass")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("invalid config must not launch a process")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert outcome.metadata_path is None


def test_non_string_hook_warns_without_launching(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, ["true"], timeout=5.0)
    harness.fake_classify("pass")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("invalid config must not launch a process")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert "after_rebase" in outcome.decision["reason"]


def test_facade_failure_warns_and_keeps_evidence(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(
        tmp_path / "clean.py", exit_code=0, report=make_report("clean")
    )
    harness.configure(root, hook)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("binding exploded")

    harness.monkeypatch.setattr(
        "sase.core.rebase_gate.classify_rebase_gate_result", broken
    )
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert "binding exploded" in (outcome.decision["diagnostics"] or "")
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "warned"


def test_config_load_failure_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    def broken(path: Path) -> dict[str, Any]:
        raise RuntimeError("config store exploded")

    harness.monkeypatch.setattr(runner, "load_merged_config_for_local_path", broken)
    harness.fake_classify("pass")
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert outcome.metadata_path is None

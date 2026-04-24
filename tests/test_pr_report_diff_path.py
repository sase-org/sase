"""Tests for diff_path emission from the pr xprompt report step (bash)."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

_PR_YML = Path(__file__).resolve().parents[1] / "src" / "sase" / "xprompts" / "pr.yml"


def _report_bash_source() -> str:
    with open(_PR_YML) as f:
        data = yaml.safe_load(f)
    for step in data["steps"]:
        if step["name"] == "report":
            return str(step["bash"])
    raise AssertionError("report step not found in pr.yml")


def _run_report_bash(commit_result: dict) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        result_path = os.path.join(tmpdir, "commit_result.json")
        with open(result_path, "w") as f:
            json.dump(commit_result, f)

        proc = subprocess.run(
            ["bash", "-c", _report_bash_source()],
            capture_output=True,
            text=True,
            env={**os.environ, "SASE_ARTIFACTS_DIR": tmpdir},
        )
        assert proc.returncode == 0, f"Script failed: {proc.stderr}"
        out: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v
        return out


class TestPrReportStep:
    def test_emits_diff_path_and_pr_metadata(self) -> None:
        result = _run_report_bash(
            {
                "result": "https://example.com/pr/1",
                "message": "feat: X\n\nbody",
                "changespec_name": "proj_cs_1",
                "diff_path": "/tmp/artifacts/commit_diff.diff",
            }
        )
        assert result["diff_path"] == "/tmp/artifacts/commit_diff.diff"
        assert result["meta_pr_url"] == "https://example.com/pr/1"
        assert result["meta_pr_header"] == "feat: X"
        assert result["meta_changespec"] == "proj_cs_1"

    def test_no_diff_path_when_absent(self) -> None:
        result = _run_report_bash(
            {
                "result": "https://example.com/pr/1",
                "message": "feat: X",
                "changespec_name": "proj_cs_1",
            }
        )
        assert "diff_path" not in result


class TestPrReportIsLastPostStep:
    def test_report_is_last_step_with_path_output(self) -> None:
        with open(_PR_YML) as f:
            data = yaml.safe_load(f)
        last = data["steps"][-1]
        assert last["name"] == "report"
        assert "diff_path" in last["output"]
        assert last["output"]["diff_path"] == "path"

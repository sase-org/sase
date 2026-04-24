"""Tests for diff_path and meta_* emission from the propose xprompt report step."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

_PROPOSE_YML = (
    Path(__file__).resolve().parents[1] / "src" / "sase" / "xprompts" / "propose.yml"
)


def _report_python_source() -> str:
    with open(_PROPOSE_YML) as f:
        data = yaml.safe_load(f)
    for step in data["steps"]:
        if step["name"] == "report":
            return str(step["python"])
    raise AssertionError("report step not found in propose.yml")


def _run_report_python(commit_result: dict) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        result_path = os.path.join(tmpdir, "commit_result.json")
        with open(result_path, "w") as f:
            json.dump(commit_result, f)

        proc = subprocess.run(
            ["python3", "-c", _report_python_source()],
            capture_output=True,
            text=True,
            env={**os.environ, "SASE_ARTIFACTS_DIR": tmpdir},
        )
        assert proc.returncode == 0, f"Script failed: {proc.stderr}"
        return json.loads(proc.stdout.strip())


class TestProposeReportStep:
    def test_emits_diff_path_and_proposal_id(self) -> None:
        result = _run_report_python(
            {
                "entry_id": "p42",
                "message": "fix: bug",
                "diff_path": "/tmp/artifacts/commit_diff.diff",
            }
        )
        assert result["diff_path"] == "/tmp/artifacts/commit_diff.diff"
        assert result["meta_proposal_id"] == "p42"
        assert result["meta_commit_message"] == "fix: bug"

    def test_no_diff_path_when_absent(self) -> None:
        result = _run_report_python(
            {
                "entry_id": "p42",
                "message": "fix: bug",
            }
        )
        assert "diff_path" not in result
        assert result["meta_proposal_id"] == "p42"

    def test_no_meta_proposal_id_when_entry_id_missing(self) -> None:
        result = _run_report_python(
            {
                "message": "fix: bug",
            }
        )
        assert "meta_proposal_id" not in result
        assert result["meta_commit_message"] == "fix: bug"


class TestProposeReportIsLastPostStep:
    """The last post-step's path output is what _collect_embedded_step_outputs extracts."""

    def test_report_is_last_step_with_path_output(self) -> None:
        with open(_PROPOSE_YML) as f:
            data = yaml.safe_load(f)
        last = data["steps"][-1]
        assert last["name"] == "report"
        assert "diff_path" in last["output"]
        assert last["output"]["diff_path"] == "path"

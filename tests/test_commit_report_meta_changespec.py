"""Tests for meta_changespec and diff_path emission from the commit xprompt report step."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

_COMMIT_YML = (
    Path(__file__).resolve().parents[1] / "src" / "sase" / "xprompts" / "commit.yml"
)


def _report_python_source() -> str:
    """Extract the `report` step's python source from commit.yml."""
    with open(_COMMIT_YML) as f:
        data = yaml.safe_load(f)
    for step in data["steps"]:
        if step["name"] == "report":
            return str(step["python"])
    raise AssertionError("report step not found in commit.yml")


def _run_report_python(commit_result: dict) -> dict[str, str]:
    """Run the commit report Python script and return emitted fields."""
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


class TestCommitReportMetaChangespec:
    """Verify meta_changespec is emitted from commit_result.json."""

    def test_emits_changespec_from_changespec_name(self) -> None:
        result = _run_report_python(
            {
                "result": "abc123",
                "message": "fix: bug",
                "changespec_name": "proj_feat_1",
                "name": "feat-branch",
            }
        )
        assert result["meta_changespec"] == "proj_feat_1"
        assert result["meta_new_commit"] == "abc123"

    def test_falls_back_to_name_when_no_changespec_name(self) -> None:
        result = _run_report_python(
            {
                "result": "abc123",
                "message": "fix: bug",
                "changespec_name": None,
                "name": "feat-branch",
            }
        )
        assert result["meta_changespec"] == "feat-branch"

    def test_no_meta_changespec_when_both_empty(self) -> None:
        result = _run_report_python(
            {
                "result": "abc123",
                "message": "fix: bug",
                "changespec_name": None,
                "name": None,
            }
        )
        assert "meta_changespec" not in result

    def test_changespec_name_preferred_over_name(self) -> None:
        """changespec_name takes priority over name."""
        result = _run_report_python(
            {
                "result": "def456",
                "message": "feat: new",
                "changespec_name": "proj_cs_1",
                "name": "branch-name",
            }
        )
        assert result["meta_changespec"] == "proj_cs_1"

    def test_multiline_commit_message_preserved(self) -> None:
        """Full multi-line commit message passes through intact."""
        msg = "feat: add feature\n\nThis is the body.\nWith multiple lines."
        result = _run_report_python(
            {
                "result": "abc123",
                "message": msg,
            }
        )
        assert result["meta_commit_message"] == msg


class TestCommitReportDiffPath:
    """Verify diff_path is emitted from commit_result.json."""

    def test_emits_diff_path_when_present(self) -> None:
        result = _run_report_python(
            {
                "result": "abc123",
                "message": "fix: bug",
                "diff_path": "/tmp/artifacts/commit_diff.diff",
            }
        )
        assert result["diff_path"] == "/tmp/artifacts/commit_diff.diff"

    def test_no_diff_path_when_absent(self) -> None:
        result = _run_report_python(
            {
                "result": "abc123",
                "message": "fix: bug",
            }
        )
        assert "diff_path" not in result

    def test_no_diff_path_when_empty(self) -> None:
        result = _run_report_python(
            {
                "result": "abc123",
                "message": "fix: bug",
                "diff_path": "",
            }
        )
        assert "diff_path" not in result

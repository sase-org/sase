"""Tests for meta_changespec emission from the commit xprompt report step."""

import json
import os
import subprocess
import tempfile


def _run_report_python(commit_result: dict) -> dict[str, str]:
    """Run the commit report Python script and return emitted meta_* fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result_path = os.path.join(tmpdir, "commit_result.json")
        with open(result_path, "w") as f:
            json.dump(commit_result, f)

        # Replicate the report step's Python logic
        script = """\
import json, os
artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
result_file = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
if not result_file or not os.path.isfile(result_file):
    print("{}")
else:
    with open(result_file) as f:
        d = json.load(f)
    out = {}
    result = d.get("result", "") or ""
    message = d.get("message", "") or ""
    changespec_name = d.get("changespec_name", "") or ""
    name = d.get("name", "") or ""
    if result:
        out["meta_new_commit"] = result
    if message:
        out["meta_commit_message"] = message
    cs = changespec_name or name
    if cs:
        out["meta_changespec"] = cs
    print(json.dumps(out))
"""
        proc = subprocess.run(
            ["python3", "-c", script],
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

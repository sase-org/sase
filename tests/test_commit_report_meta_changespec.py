"""Tests for meta_changespec emission from the commit xprompt report step."""

import json
import os
import subprocess
import tempfile


def _run_report_bash(commit_result: dict) -> dict[str, str]:
    """Run the commit report bash script and return emitted meta_* lines as a dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result_path = os.path.join(tmpdir, "commit_result.json")
        with open(result_path, "w") as f:
            json.dump(commit_result, f)

        # Replicate the report step's bash logic
        script = """\
RESULT_FILE="${SASE_ARTIFACTS_DIR}/commit_result.json"
[ -f "$RESULT_FILE" ] || exit 0
eval "$(RESULT_FILE="$RESULT_FILE" python3 -c "
import json, os, shlex
with open(os.environ['RESULT_FILE']) as f:
    d = json.load(f)
for k in ('result', 'message', 'changespec_name', 'name'):
    print(f'{k}={shlex.quote(d.get(k, \\\"\\\") or \\\"\\\")}')
")"
[ -n "$result" ] && echo "meta_new_commit=$result"
[ -n "$message" ] && echo "meta_commit_message=$message"
if [ -n "$changespec_name" ]; then echo "meta_changespec=$changespec_name"; elif [ -n "$name" ]; then echo "meta_changespec=$name"; fi
"""
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "SASE_ARTIFACTS_DIR": tmpdir},
        )
        assert proc.returncode == 0, f"Script failed: {proc.stderr}"

        meta: dict[str, str] = {}
        for line in proc.stdout.strip().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                meta[key] = value
        return meta


class TestCommitReportMetaChangespec:
    """Verify meta_changespec is emitted from commit_result.json."""

    def test_emits_changespec_from_changespec_name(self) -> None:
        result = _run_report_bash(
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
        result = _run_report_bash(
            {
                "result": "abc123",
                "message": "fix: bug",
                "changespec_name": None,
                "name": "feat-branch",
            }
        )
        assert result["meta_changespec"] == "feat-branch"

    def test_no_meta_changespec_when_both_empty(self) -> None:
        result = _run_report_bash(
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
        result = _run_report_bash(
            {
                "result": "def456",
                "message": "feat: new",
                "changespec_name": "proj_cs_1",
                "name": "branch-name",
            }
        )
        assert result["meta_changespec"] == "proj_cs_1"

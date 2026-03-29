"""Regression tests for #pr report step exit-code behavior.

The report step in pr.yml parses commit_result.json and emits optional
meta_* keys.  Previously, trailing ``[ -n "$var" ] && echo ...`` caused
exit 1 when the variable was empty, failing the workflow step even though
the PR was created successfully.
"""

import json
import subprocess
from pathlib import Path

# The shell logic mirrors src/sase/xprompts/pr.yml "report" step.
# Written to a temp file at runtime to avoid nested-quoting issues.
_REPORT_SCRIPT = r"""
RESULT_FILE="$1"
[ -f "$RESULT_FILE" ] || exit 0
eval "$(RESULT_FILE="$RESULT_FILE" python3 -c "
import json, os, shlex
with open(os.environ['RESULT_FILE']) as f:
    d = json.load(f)
for k in ('result', 'message', 'changespec_name'):
    print(f'{k}={shlex.quote(d.get(k, \"\") or \"\")}')
")"
if [ -n "$message" ]; then
  header=$(echo "$message" | head -1)
  echo "meta_pr_header=$header"
fi
if [ -n "$result" ]; then
  echo "meta_pr_url=$result"
fi
if [ -n "$changespec_name" ]; then
  echo "meta_changespec=$changespec_name"
fi
"""


def _run_report(
    tmp_path: Path, payload: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    result_file = tmp_path / "commit_result.json"
    result_file.write_text(json.dumps(payload))
    script_file = tmp_path / "report.sh"
    script_file.write_text(_REPORT_SCRIPT)
    return subprocess.run(
        ["bash", "-e", str(script_file), str(result_file)],
        capture_output=True,
        text=True,
    )


class TestPrReportStep:
    """Verify report step exits 0 and emits correct meta keys."""

    def test_all_fields_present(self, tmp_path: Path) -> None:
        proc = _run_report(
            tmp_path,
            {
                "result": "https://github.com/org/repo/pull/42",
                "message": "feat: add widget\n\nBody text",
                "changespec_name": "widget_feature",
            },
        )
        assert proc.returncode == 0
        assert "meta_pr_header=feat: add widget" in proc.stdout
        assert "meta_pr_url=https://github.com/org/repo/pull/42" in proc.stdout
        assert "meta_changespec=widget_feature" in proc.stdout

    def test_missing_changespec(self, tmp_path: Path) -> None:
        proc = _run_report(
            tmp_path,
            {
                "result": "https://github.com/org/repo/pull/7",
                "message": "fix: patch thing",
            },
        )
        assert proc.returncode == 0
        assert "meta_pr_url=https://github.com/org/repo/pull/7" in proc.stdout
        assert "meta_changespec" not in proc.stdout

    def test_missing_result(self, tmp_path: Path) -> None:
        proc = _run_report(
            tmp_path,
            {
                "message": "chore: tidy up",
                "changespec_name": "tidy",
            },
        )
        assert proc.returncode == 0
        assert "meta_pr_header=chore: tidy up" in proc.stdout
        assert "meta_pr_url" not in proc.stdout
        assert "meta_changespec=tidy" in proc.stdout

    def test_missing_message(self, tmp_path: Path) -> None:
        proc = _run_report(
            tmp_path,
            {
                "result": "https://github.com/org/repo/pull/99",
            },
        )
        assert proc.returncode == 0
        assert "meta_pr_header" not in proc.stdout
        assert "meta_pr_url=https://github.com/org/repo/pull/99" in proc.stdout

    def test_all_optional_fields_empty(self, tmp_path: Path) -> None:
        proc = _run_report(tmp_path, {})
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_no_result_file(self, tmp_path: Path) -> None:
        """Script exits 0 when commit_result.json does not exist."""
        script_file = tmp_path / "report.sh"
        script_file.write_text(_REPORT_SCRIPT)
        proc = subprocess.run(
            ["bash", "-e", str(script_file), str(tmp_path / "missing.json")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

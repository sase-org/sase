"""Tests for ``tools/check_rebase_imports`` (phase sase-1pm.5.1.3).

Import resolution runs in isolated subprocesses against tiny fake ``sase``
packages so the checker cannot pick up this checkout's installed package.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_rebase_imports"
HELPER = ROOT / "tools" / "_check_rebase_imports.py"
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import _check_rebase_imports as rebase_imports  # noqa: E402

FAKE_HEAD = "a" * 40
FAKE_TREE = "b" * 40


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo, ".gitignore", "__pycache__/\n*.pyc\n")
    for rel, content in files.items():
        _write(repo, rel, content)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _ids(repo: Path) -> tuple[str, str]:
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
    return head, tree


def _change(
    path: str, kind: str = "modified", old_path: str | None = None
) -> dict[str, str]:
    payload = {"path": path, "kind": kind}
    if old_path is not None:
        payload["old_path"] = old_path
    return payload


def _context(
    repo: Path,
    changed: list[dict[str, str]],
    *,
    head: str | None = None,
    tree: str | None = None,
) -> dict[str, Any]:
    current_head, current_tree = _ids(repo)
    return {
        "schema_version": 1,
        "repository_root": str(repo),
        "inputs": [
            {
                "old_head": FAKE_HEAD,
                "upstream_tip": FAKE_TREE,
                "merge_base": "c" * 40,
            }
        ],
        "current_head": head or current_head,
        "current_tree": tree or current_tree,
        "changed_paths": changed,
    }


def _base_files(**extra: str) -> dict[str, str]:
    files = {
        "src/sase/__init__.py": "",
        "src/sase/mod.py": "Present = 1\n_X = 1\n",
        "src/sase/pkg/__init__.py": "from sase.pkg.inner import Reexported\n",
        "src/sase/pkg/inner.py": "Reexported = 1\n",
        "src/sase/pkg/sub.py": "value = 1\n",
    }
    files.update(extra)
    return files


def _run_tool(
    repo: Path,
    context: dict[str, Any],
    *,
    extra_env: dict[str, str] | None = None,
    exceptions: list[list[str]] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    ctx_path = repo / "rebase-context.json"
    result_path = repo / "rebase-result.json"
    ctx_path.write_text(json.dumps(context), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env[rebase_imports.CONTEXT_ENV] = str(ctx_path)
    env[rebase_imports.RESULT_ENV] = str(result_path)
    if extra_env:
        env.update(extra_env)
    if exceptions is None:
        command = [sys.executable, str(TOOL)]
    else:
        command = [
            sys.executable,
            "-c",
            "import json, sys\n"
            f"sys.path.insert(0, {str(HELPER.parent)!r})\n"
            "import _check_rebase_imports as m\n"
            "m.TYPE_CHECKING_ALIAS_EXCEPTIONS = frozenset(\n"
            f"    (a, b) for a, b in json.loads({json.dumps(json.dumps(exceptions))})\n"
            ")\n"
            "raise SystemExit(m.main())\n",
        ]
    proc = subprocess.run(
        command,
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    report = None
    if result_path.is_file():
        report = json.loads(result_path.read_text(encoding="utf-8"))
    return proc, report


def test_tool_script_is_executable() -> None:
    assert TOOL.is_file()
    assert TOOL.stat().st_mode & stat.S_IXUSR
    assert HELPER.is_file()


def test_helper_never_imports_sase() -> None:
    text = HELPER.read_text(encoding="utf-8")
    assert "import sase" not in text
    assert "from sase" not in text


def test_collect_import_sites_covers_nested_and_type_checking() -> None:
    source = """\
from __future__ import annotations
from typing import TYPE_CHECKING
import os
from sase.mod import Top
from sase.mod import Star as Alias
from sase.pkg import sub
from sase.gone import *

def outer():
    from sase.mod import Inner
    def nested():
        from sase.mod import Nested

class Body:
    from sase.mod import ClassName

if TYPE_CHECKING:
    from sase.mod import TypingOnly
    from sase.mod import TypingOnly as AliasToo
else:
    from sase.mod import RuntimeElse
"""
    sites = rebase_imports.collect_import_sites(source, "src/sase/importer.py")
    pairs = [(site.module, site.imported_name, site.in_type_checking) for site in sites]
    assert ("sase.mod", "Top", False) in pairs
    assert ("sase.mod", "Star", False) in pairs
    assert ("sase.pkg", "sub", False) in pairs
    assert ("sase.gone", "*", False) in pairs
    assert ("sase.mod", "Inner", False) in pairs
    assert ("sase.mod", "Nested", False) in pairs
    assert ("sase.mod", "ClassName", False) in pairs
    assert ("sase.mod", "TypingOnly", True) in pairs
    assert ("sase.mod", "RuntimeElse", False) in pairs
    assert all(site.line > 0 for site in sites)


def test_collect_import_sites_resolves_relative_into_sase() -> None:
    source = "from .inner import Reexported\nfrom ..mod import Present\n"
    sites = rebase_imports.collect_import_sites(source, "src/sase/pkg/rel.py")
    pairs = {(site.module, site.imported_name) for site in sites}
    assert pairs == {("sase.pkg.inner", "Reexported"), ("sase.mod", "Present")}


def test_clean_reexport_and_submodule_and_star_are_ok(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(
            **{
                "src/sase/importer.py": """\
from sase.pkg import Reexported
from sase.pkg import sub
from sase.mod import *
from sase.mod import Present as Alias
"""
            }
        ),
    )
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py", "added")]),
    )
    assert proc.returncode == 0
    assert report is not None
    assert report["status"] == "clean"
    assert report["findings"] == []
    assert report["schema_version"] == 1
    assert set(report) <= {
        "schema_version",
        "checked_head",
        "checked_tree",
        "status",
        "findings",
        "diagnostics",
    }


def test_rename_incident_is_a_finding_at_every_ast_depth(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(
            **{
                "src/sase/importer.py": """\
from typing import TYPE_CHECKING
from sase.mod import X

def outer():
    from sase.mod import X
    def nested():
        from sase.mod import X

class Body:
    from sase.mod import X

if TYPE_CHECKING:
    from sase.mod import X
"""
            }
        ),
    )
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py")]),
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["status"] == "findings"
    names = {(item["imported_name"], item["module"]) for item in report["findings"]}
    assert names == {("X", "sase.mod")}
    assert len(report["findings"]) == 5
    assert all(item["path"] == "src/sase/importer.py" for item in report["findings"])
    assert all(item["line"] > 0 for item in report["findings"])
    assert all(
        "cannot import name 'X'" in item["explanation"] for item in report["findings"]
    )


def test_relative_and_removed_module_are_findings(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(
            **{
                "src/sase/pkg/rel.py": "from .missing import Name\nfrom sase.gone import Missing\n"
            }
        ),
    )
    proc, report = _run_tool(
        repo,
        _context(
            repo,
            [
                _change("src/sase/pkg/rel.py"),
                _change("src/sase/gone.py", "deleted"),
                _change("README.md", "modified"),
            ],
        ),
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["status"] == "findings"
    modules = {item["module"] for item in report["findings"]}
    assert modules == {"sase.pkg.missing", "sase.gone"}


def test_inspects_both_sides_changed_files(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(
            **{
                "src/sase/local.py": "from sase.mod import LocalMissing\n",
                "tests/test_upstream.py": "from sase.mod import UpstreamMissing\n",
            }
        ),
    )
    proc, report = _run_tool(
        repo,
        _context(
            repo,
            [
                _change("src/sase/local.py", "modified"),
                _change("tests/test_upstream.py", "added"),
            ],
        ),
    )
    assert proc.returncode == 1
    assert report is not None
    paths = {item["path"] for item in report["findings"]}
    assert paths == {"src/sase/local.py", "tests/test_upstream.py"}
    imported = {item["imported_name"] for item in report["findings"]}
    assert imported == {"LocalMissing", "UpstreamMissing"}


def test_dependency_error_is_protocol_error_not_finding(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(
            **{
                "src/sase/broken.py": "import definitely_missing_third_party_xyzzy\nPresent = 1\n",
                "src/sase/importer.py": "from sase.broken import Present\n",
            }
        ),
    )
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py")]),
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["status"] == "error"
    assert report["findings"] == []
    assert "definitely_missing_third_party_xyzzy" in str(report.get("diagnostics"))


def test_stale_installed_package_does_not_satisfy_src(tmp_path: Path) -> None:
    stale = tmp_path / "site"
    _write(stale, "sase/__init__.py", "")
    _write(stale, "sase/mod.py", "X = 1\n")
    repo = _init_repo(
        tmp_path,
        _base_files(**{"src/sase/importer.py": "from sase.mod import X\n"}),
    )
    pythonpath = str(stale)
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        pythonpath = pythonpath + os.pathsep + existing
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py")]),
        extra_env={"PYTHONPATH": pythonpath},
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["status"] == "findings"
    assert report["findings"][0]["imported_name"] == "X"


def test_allowlist_skips_type_checking_only(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(
            **{
                "src/sase/importer.py": """\
from typing import TYPE_CHECKING
from sase.mod import Ghost

if TYPE_CHECKING:
    from sase.mod import Ghost
"""
            }
        ),
    )
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py")]),
        exceptions=[["sase.mod", "Ghost"]],
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["status"] == "findings"
    assert len(report["findings"]) == 1
    assert report["findings"][0]["line"] == 2
    assert report["findings"][0]["imported_name"] == "Ghost"


def test_star_import_of_missing_module_is_a_finding(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(**{"src/sase/importer.py": "from sase.gone import *\n"}),
    )
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py")]),
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["findings"][0]["imported_name"] == "*"
    assert report["findings"][0]["module"] == "sase.gone"


def test_unrelated_dirty_python_file_fails_open(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(**{"src/sase/importer.py": "from sase.mod import Present\n"}),
    )
    _write(repo, "src/sase/dirty.py", "print('dirty')\n")
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py")]),
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["status"] == "error"
    assert "does not match the committed tree" in str(report.get("diagnostics"))


def test_unstaged_repair_does_not_certify_committed_tree(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        _base_files(**{"src/sase/importer.py": "from sase.mod import X\n"}),
    )
    _write(repo, "src/sase/importer.py", "from sase.mod import Present\n")
    proc, report = _run_tool(
        repo,
        _context(repo, [_change("src/sase/importer.py")]),
    )
    assert proc.returncode == 1
    assert report is not None
    assert report["status"] == "error"
    assert "does not match the committed tree" in str(report.get("diagnostics"))


def test_missing_env_exits_without_pretending_clean(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(TOOL)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert rebase_imports.CONTEXT_ENV in proc.stderr

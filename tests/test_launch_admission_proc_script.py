"""Proc dispatch script preparation: argv construction and digest verification."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from sase.core.agent_launch_facade import prepare_proc_script, proc_script_argv
from sase.xprompt.code_value import make_code_value


def test_proc_script_argv_is_not_interpolated_from_source(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.core.agent_launch_facade import proc_dispatch_wire_schema_version

    work = tmp_path / "work"
    work.mkdir()
    hostile = 'echo ready; rm -rf /; $(reboot); `id`; echo "$HOME"'
    code = make_code_value(hostile, "bash", "bash")
    prepared = prepare_proc_script(
        {
            "schema_version": proc_dispatch_wire_schema_version(),
            "logical_id": "unit-1",
            "fingerprint": "fp",
            "code": {
                "schema_version": 1,
                "source": code.source,
                "language": code.language,
                "digest": code.digest,
                "preview": code.preview,
            },
            "work_dir": str(work),
            "python_executable": sys.executable,
            "workspace": False,
            "declared_cwd": str(tmp_path),
            "source_cwd": str(tmp_path),
            "proc_id": "proc-argv",
        }
    )
    argv = list(prepared["argv"])
    assert argv[:3] == ["/bin/bash", "--noprofile", "--norc"]
    assert hostile not in " ".join(argv)
    script = Path(str(prepared["script_path"]))
    assert stat.S_IMODE(script.stat().st_mode) == 0o600
    assert script.read_text(encoding="utf-8") == hostile
    assert argv == proc_script_argv("bash", str(work), sys.executable)


def test_prepare_proc_script_rejects_digest_mismatch(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.core.agent_launch_facade import proc_dispatch_wire_schema_version

    work = tmp_path / "work"
    work.mkdir()
    code = make_code_value("echo ready", "bash", "bash")
    with pytest.raises(Exception, match="digest"):
        prepare_proc_script(
            {
                "schema_version": proc_dispatch_wire_schema_version(),
                "logical_id": "unit-1",
                "fingerprint": "fp",
                "code": {
                    "schema_version": 1,
                    "source": code.source,
                    "language": code.language,
                    "digest": "0" * 64,
                    "preview": code.preview,
                },
                "work_dir": str(work),
                "python_executable": sys.executable,
                "workspace": False,
                "declared_cwd": str(tmp_path),
                "source_cwd": str(tmp_path),
                "proc_id": "proc-digest",
            }
        )

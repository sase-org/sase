"""Sudo acceptance coverage for credential-leak boundaries."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import canonical_json_bytes
from sase.notification_gates.service import create_gate
from sase.sudo import runner as sudo_runner
from sase.sudo.cli import handle_sudo_command
from sase.sudo.gate import build_sudo_gate_request
from tests._sudo_acceptance_helpers import (
    _CANARY,
    _assert_sensitive_tokens_absent,
    _assert_sensitive_tokens_absent_bytes,
    _request,
    _runner_ledger,
    _sensitive_tokens,
)


def test_sudo_local_flow_never_persists_canary_credentials(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    credential_tty = tmp_path / "review-terminal-input.txt"
    credential_tty.write_text(_CANARY, encoding="utf-8")
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    with override_flags(agent_sudo_requests=True):
        gate = create_gate(
            build_sudo_gate_request(_request(), request_id="sudo-canary-flow")
        )

    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach", "--json"]
    )
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )

    def fake_runner(
        manifest: Mapping[str, Any],
        *,
        manifest_sha256: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        assert credential_tty.read_text(encoding="utf-8") == _CANARY
        manifest_bytes = canonical_json_bytes(dict(manifest))
        for token in _sensitive_tokens(_CANARY).values():
            assert token not in manifest_bytes
        return _runner_ledger(manifest, manifest_sha256)

    monkeypatch.setattr("sase.sudo.cli.run_sudo_runner", fake_runner)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "answered"
    assert output["outcome"] == "completed"
    assert gate.response_path.is_file()
    assert (gate.bundle_path / DECISION_RECEIPT_FILENAME).is_file()
    _assert_sensitive_tokens_absent(
        (
            gate_home / "requests",
            gate_home / "notifications",
            gate_home / "pending.json",
            gate_home / "legacy.json",
            sase_home,
        ),
        canary=_CANARY,
    )


def test_sudo_runner_invocation_keeps_canary_out_of_process_argv_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not Path("/proc").is_dir():
        pytest.skip("/proc is required for argv and environment inspection")
    credential_tty = tmp_path / "review-terminal-input.txt"
    credential_tty.write_text(_CANARY, encoding="utf-8")
    fake_bin = tmp_path / "venv" / "bin"
    fake_bin.mkdir(parents=True)
    fake_runner = fake_bin / "sase_sudo_runner"
    fake_runner.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "import sys",
                "import time",
                "with open(os.environ['SASE_FAKE_TTY_PATH'], encoding='utf-8') as handle:",
                "    handle.read()",
                "time.sleep(0.25)",
                "sha = sys.argv[sys.argv.index('--expected-sha256') + 1]",
                "print(json.dumps({'ok': True, 'manifest_sha256': sha}))",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_runner.chmod(0o755)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"schema_version": 1}\n', encoding="utf-8")
    captured: dict[str, bytes] = {}
    real_popen = subprocess.Popen

    def inspected_run(
        argv: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        process = real_popen(
            argv,
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            text=kwargs.get("text", False),
        )
        try:
            captured["cmdline"] = Path(f"/proc/{process.pid}/cmdline").read_bytes()
            captured["environ"] = Path(f"/proc/{process.pid}/environ").read_bytes()
            stdout, stderr = process.communicate(timeout=kwargs.get("timeout"))
        except BaseException:
            process.kill()
            raise
        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(sudo_runner.sys, "executable", str(fake_bin / "python"))
    monkeypatch.setenv("SASE_FAKE_TTY_PATH", str(credential_tty))
    monkeypatch.setattr(sudo_runner.subprocess, "run", inspected_run)

    assert sudo_runner.run_sudo_runner_file(
        manifest,
        manifest_sha256="abc123",
    ) == {"ok": True, "manifest_sha256": "abc123"}
    _assert_sensitive_tokens_absent_bytes(captured.values(), canary=_CANARY)

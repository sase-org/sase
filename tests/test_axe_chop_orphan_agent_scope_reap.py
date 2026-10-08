"""Output-contract tests for the orphan_agent_scope_reap chop."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

from sase.chops.builtin import run_builtin_chop

from tests._axe_chop_output_contract_helpers import (
    _isolate_chop_result_file,  # noqa: F401 (registers the result-file isolation fixture)
    _write_context,
)


def _empty_result() -> SimpleNamespace:
    return SimpleNamespace(
        scanned=0,
        live=0,
        skipped_young=0,
        spared_only=0,
        reaped_scopes=0,
        reaped=(),
        terminated=0,
        errors=0,
    )


def test_orphan_agent_scope_reap_emits_noop_summary(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_orphan_agent_scope_reap")

    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(script, "get_agent_scope_teardown_enabled", lambda: True)
    monkeypatch.setattr(
        script, "reap_orphaned_agent_scopes", lambda **_kwargs: _empty_result()
    )

    run_builtin_chop("orphan_agent_scope_reap", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "orphan_agent_scope_reap:" in out
    assert "reaped_scopes=0" in out
    assert "terminated=0" in out
    assert "reason=nothing_eligible" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_eligible"
    assert result["counters"] == {
        "scanned": 0,
        "live": 0,
        "skipped_young": 0,
        "spared_only": 0,
        "reaped_scopes": 0,
        "terminated": 0,
        "errors": 0,
    }


def test_orphan_agent_scope_reap_emits_action_summary(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_orphan_agent_scope_reap")

    reaped = SimpleNamespace(
        unit="sase-agent-9-123.scope",
        agent_name="agent-x",
        targets=2,
        terminated=2,
        entries=("1 sh busy",),
    )
    fake = SimpleNamespace(
        scanned=3,
        live=1,
        skipped_young=1,
        spared_only=0,
        reaped_scopes=1,
        reaped=(reaped,),
        terminated=2,
        errors=0,
    )
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(script, "get_agent_scope_teardown_enabled", lambda: True)
    monkeypatch.setattr(script, "reap_orphaned_agent_scopes", lambda **_kwargs: fake)

    run_builtin_chop("orphan_agent_scope_reap", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "orphan_agent_scope_reap:" in out
    assert "reaped_scopes=1" in out
    assert "terminated=2" in out
    assert "sase-agent-9-123.scope" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"]["reaped_scopes"] == 1
    assert result["counters"]["terminated"] == 2
    assert result["counters"]["scanned"] == 3


def test_orphan_agent_scope_reap_reports_disabled(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    importlib.import_module("sase.scripts.sase_chop_orphan_agent_scope_reap")

    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    import sase.scripts.sase_chop_orphan_agent_scope_reap as script

    monkeypatch.setattr(script, "get_agent_scope_teardown_enabled", lambda: False)
    called: list[bool] = []
    monkeypatch.setattr(
        script,
        "reap_orphaned_agent_scopes",
        lambda **_kwargs: called.append(True) or _empty_result(),
    )

    run_builtin_chop("orphan_agent_scope_reap", ["--context", str(context_path)])

    assert called == []
    out = capsys.readouterr().out
    assert "reason=disabled" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "disabled"

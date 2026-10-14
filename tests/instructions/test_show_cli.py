"""CLI tests for ``sase instructions show``."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sase.agent.names._common import NamedAgent
from sase.instructions.show import run_instructions_show
from sase.main.parser import create_parser
from tests.instructions.fixture_shadow import write_helper_shadow, write_shadow_run
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented as _assert_metavar_option_documented,
)
from tests.main.parser_help_helpers import flat_help, parser_for


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )


def _named(name: str, artifacts: Path) -> NamedAgent:
    return NamedAgent(
        name=name, artifacts_dir=str(artifacts), is_done=True, outcome="dismissed"
    )


def _write_meta(
    artifacts: Path, *, name: str, provider: str, manifest: dict[str, object]
) -> None:
    bundle = manifest["bundle"]
    assert isinstance(bundle, dict)
    delivery = manifest["delivery"]
    assert isinstance(delivery, dict)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "llm_provider": provider,
                "workspace_dir": "/work/synthetic",
                "run_started_at": "2026-10-01T12:00:00Z",
                "instructions": {
                    "count": 1,
                    "latest": {
                        "seq": delivery.get("invocation_seq", 0),
                        "provider": provider,
                        "purpose": "ordinary",
                        "sha256": bundle["sha256"],
                        "common_digest": bundle["common_digest"],
                        "manifest": f"instructions/00-{provider}.json",
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_show_parser_options_are_alphabetical_with_short_aliases() -> None:
    """Every ``show`` value-taking option keeps its short alias."""
    args = create_parser().parse_args(
        [
            "instructions",
            "show",
            "some-agent",
            "-H",
            "-j",
            "-l",
            "-n",
            "1",
            "-s",
        ]
    )
    assert args.instructions_subcommand == "show"
    assert args.agent == "some-agent"
    assert args.helper is True
    assert args.json is True
    assert args.list is True
    assert args.seq == 1
    assert args.sections is True


def test_show_help_documents_flags() -> None:
    """``show -h`` names every option and the integrity contract."""
    help_text = flat_help(parser_for(("sase", "instructions", "show")).format_help())
    for flag in ("-H, --helper", "-j, --json", "-l, --list", "-s, --sections"):
        assert flag in help_text
    _assert_metavar_option_documented(help_text, "-n", "--seq", "NN")
    assert "bytes match" in help_text or "sha256" in help_text
    assert "NAME" in help_text


def test_show_unknown_agent_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name that resolves to nothing prints ``unknown agent NAME``."""
    monkeypatch.setattr("sase.agent.names.find_named_agent", lambda name, **_k: None)
    args = create_parser().parse_args(["instructions", "show", "ghost"])
    assert run_instructions_show(args) == 2
    assert "unknown agent ghost" in capsys.readouterr().err


def test_show_no_instructions_dir_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Runs with no ``instructions/`` print a clear note and exit 2."""
    artifacts = tmp_path / "run"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "bare",
                "llm_provider": "codex",
                "workspace_dir": "/work/synthetic",
                "run_started_at": "2026-10-01T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "bare"])
    assert run_instructions_show(args) == 2
    assert "no instructions/" in capsys.readouterr().err


def test_show_integrity_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Matching run-copy bytes print the bundle and report ``bytes match``."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path, provider="codex")
    _write_meta(artifacts, name="kept.agent", provider="codex", manifest=manifest)
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "kept.agent"])
    assert run_instructions_show(args) == 0
    captured = capsys.readouterr()
    assert (
        captured.out == bundle
        or captured.out == bundle + "\n"
        or bundle in captured.out
    )
    assert "bytes match" in captured.err


def test_show_integrity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run copy that does not match the manifest sha exits 1."""
    artifacts, manifest, _bundle = write_shadow_run(tmp_path, provider="codex")
    _write_meta(artifacts, name="bad.agent", provider="codex", manifest=manifest)
    (artifacts / "instructions" / "00-codex.md").write_text(
        "tampered\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "bad.agent"])
    assert run_instructions_show(args) == 1
    assert "MISMATCH" in capsys.readouterr().err


def test_show_store_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing run copy falls back to ``bundle.store_path``."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path, provider="codex")
    store = tmp_path / "store" / "bundle.md"
    store.parent.mkdir(parents=True)
    store.write_text(bundle, encoding="utf-8")
    manifest["bundle"]["store_path"] = str(store)
    (artifacts / "instructions" / "00-codex.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (artifacts / "instructions" / "00-codex.md").unlink()
    _write_meta(artifacts, name="store.agent", provider="codex", manifest=manifest)
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "store.agent"])
    assert run_instructions_show(args) == 0
    captured = capsys.readouterr()
    assert "bytes match" in captured.err
    assert "source=store" in captured.err
    assert hashlib.sha256(bundle.encode("utf-8")).hexdigest()[:12] in captured.err


def test_show_list_includes_root_and_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``-l`` prints one row per root and helper manifest."""
    artifacts, root, _ = write_shadow_run(tmp_path, provider="claude")
    parent_id = str(root["delivery"]["invocation_id"])
    write_helper_shadow(artifacts, provider="claude", parent_invocation_id=parent_id)
    _write_meta(artifacts, name="pair.agent", provider="claude", manifest=root)
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "pair.agent", "-l"])
    assert run_instructions_show(args) == 0
    out = capsys.readouterr().out
    assert "sase_root" in out
    assert "native_helper" in out
    assert "bytes match" in out
    assert parent_id not in out or "native_helper" in out


def test_show_json_prints_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-j`` prints the chosen manifest JSON."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="codex")
    _write_meta(artifacts, name="json.agent", provider="codex", manifest=manifest)
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "json.agent", "-j"])
    assert run_instructions_show(args) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["bundle"]["sha256"] == manifest["bundle"]["sha256"]
    assert "bytes match" in captured.err


def test_show_helper_flag_prints_helper_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``-H`` prints the helper bundle of the chosen invocation."""
    artifacts, root, _ = write_shadow_run(tmp_path, provider="claude")
    parent_id = str(root["delivery"]["invocation_id"])
    _helper, helper_bundle = write_helper_shadow(
        artifacts, provider="claude", parent_invocation_id=parent_id
    )
    _write_meta(artifacts, name="pair.agent", provider="claude", manifest=root)
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "pair.agent", "-H"])
    assert run_instructions_show(args) == 0
    captured = capsys.readouterr()
    assert helper_bundle.strip() in captured.out
    assert "helper" in captured.err
    assert "bytes match" in captured.err


def test_show_dismissed_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``show`` resolves a dismissed agent through ``find_named_agent``."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path, provider="grok")
    _write_meta(artifacts, name="261013.old", provider="grok", manifest=manifest)
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    args = create_parser().parse_args(["instructions", "show", "261013.old"])
    assert run_instructions_show(args) == 0
    captured = capsys.readouterr()
    assert bundle.strip() in captured.out
    assert "bytes match" in captured.err

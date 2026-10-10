"""Code-identity, refresh-line, and proof-target tests for the scan phase.

Split from ``tests.test_agent_auto_restart_scan``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from sase.agent.auto_restart.managed_roots import code_identity_digest
from sase.agent.auto_restart.witnesses import (
    _extract_proof_target,
    _parse_refresh_log_line,
    _select_proof_root,
)
from tests._agent_auto_restart_scan_helpers import scan_facts, scan_managed_roots

__all__ = [
    "test_code_identity_digest_detects_drift",
    "test_code_identity_digest_none_without_roots",
    "test_code_identity_digest_prefers_commit_over_version",
    "test_code_identity_digest_stable_without_drift",
    "test_extract_proof_target_from_attribute_error",
    "test_extract_proof_target_from_error_text",
    "test_extract_proof_target_from_structured_facts",
    "test_extract_proof_target_unknown",
    "test_parse_refresh_log_line",
    "test_parse_refresh_log_line_missing",
    "test_select_proof_root",
]


def test_code_identity_digest_detects_drift() -> None:
    boot = {"roots": [{"name": "sase", "commit": "9c5000f2db"}]}
    current = {"roots": [{"name": "sase", "commit": "9fd8a081f4"}]}
    assert code_identity_digest(boot) != code_identity_digest(current)


def test_code_identity_digest_stable_without_drift() -> None:
    identity = {
        "roots": [
            {"name": "sase", "commit": "9fd8a081f4"},
            {"name": "sase-core-rs", "version": "0.37.2"},
        ]
    }
    assert code_identity_digest(identity) == code_identity_digest(identity)


def test_code_identity_digest_prefers_commit_over_version() -> None:
    identity = {"roots": [{"name": "sase", "commit": "9fd8a081f4", "version": "9.9.9"}]}
    assert code_identity_digest(identity) == "sase@9fd8a08"


def test_code_identity_digest_none_without_roots() -> None:
    assert code_identity_digest(None) is None
    assert code_identity_digest({}) is None
    assert code_identity_digest({"roots": []}) is None
    assert code_identity_digest({"roots": [{"name": ""}]}) is None


def test_parse_refresh_log_line() -> None:
    tail = (
        "Waiting for agents: research.46.final\n"
        "Refreshing sase runner code after dependency wait: "
        "9c5000f2dbb126962ea0a84856d0a49115450dc7 "
        "-> 9fd8a081f45689655249b7bf6ed7b561de65b8bf\n"
        "Error running agent: boom\n"
    )
    line = _parse_refresh_log_line(tail)
    assert line is not None
    assert line.from_rev == "9c5000f2dbb126962ea0a84856d0a49115450dc7"
    assert line.to_rev == "9fd8a081f45689655249b7bf6ed7b561de65b8bf"


def test_parse_refresh_log_line_missing() -> None:
    assert _parse_refresh_log_line("nothing here\n") is None
    assert _parse_refresh_log_line("") is None


def test_extract_proof_target_from_structured_facts() -> None:
    module, symbol = _extract_proof_target(
        scan_facts(), error_text="", traceback_text=""
    )
    assert module == "sase.monitor.continuation_delivery"
    assert symbol == "auto_launch_prefix"


def test_extract_proof_target_from_attribute_error() -> None:
    facts = scan_facts()
    facts["import_error"] = None
    facts["attribute_error"] = {
        "module": "sase.monitor.continuation_delivery",
        "attribute": "auto_launch_prefix",
    }
    module, symbol = _extract_proof_target(facts, error_text="", traceback_text="")
    assert module == "sase.monitor.continuation_delivery"
    assert symbol == "auto_launch_prefix"


def test_extract_proof_target_from_error_text() -> None:
    module, symbol = _extract_proof_target(
        None,
        error_text=("ImportError: cannot import name 'gone' from 'sase.foo.bar'"),
        traceback_text="",
    )
    assert module == "sase.foo.bar"
    assert symbol == "gone"


def test_extract_proof_target_unknown() -> None:
    assert _extract_proof_target(None, error_text="boom", traceback_text="") == (
        None,
        None,
    )
    assert _extract_proof_target({}, error_text="", traceback_text="") == (
        None,
        None,
    )


def test_select_proof_root() -> None:
    roots = scan_managed_roots()
    host = _select_proof_root("sase.monitor.x", roots)
    assert host is not None and host.name == "sase"
    core = _select_proof_root("sase_core_rs", roots)
    assert core is not None and core.name == "sase-core-rs"
    assert _select_proof_root("requests.models", roots) is None
    assert _select_proof_root(None, roots) is None
    assert _select_proof_root("sase.x", ()) is None

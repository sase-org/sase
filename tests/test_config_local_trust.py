"""Trust-policy contract tests: Rust projection, digest, filtering, decision.

Phase ``trust-policy`` is additive: no runtime loader is filtered here.
These tests exercise the thin adapter in :mod:`sase.config.local_trust`
against the real ``sase_core_rs`` bindings with temporary decoded data.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from sase.config.local_trust import (
    LOCAL_COMMAND_DIGEST_DOMAIN,
    LOCAL_COMMAND_TRUST_POLICY_VERSION,
    LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION,
    decide_local_command_trust,
    digest_local_commands,
    filter_trusted_local_layer,
    local_command_trust_wire_schema_version,
    project_local_commands,
)

sase_core_rs = pytest.importorskip("sase_core_rs")


def test_wire_schema_version_matches_rust() -> None:
    """Python mirror constant tracks the Rust binding version."""
    assert local_command_trust_wire_schema_version() == (
        LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION
    )
    assert sase_core_rs.local_command_trust_wire_schema_version() == (
        LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION
    )


def test_empty_and_non_command_layers_share_digest() -> None:
    """Ordinary local values never enter the command-bearing projection."""
    empty = project_local_commands({})
    display_only = project_local_commands(
        {
            "timezone": "UTC",
            "alias": "x",
            "ace": {"prompt_completion": {"auto_macro_menu": False}},
            "macros": {"hello": "world"},
        }
    )
    assert empty.projection == {}
    assert display_only.projection == {}
    assert empty.digest == display_only.digest
    assert empty.blocked_paths == ()


def test_legacy_macro_spellings_normalize_before_classification() -> None:
    """Retired ``xprompts`` spellings hash and filter as ``macros``."""
    legacy = project_local_commands(
        {"xprompts": {"hello": "world"}},
        source="local",
    )
    assert legacy.projection == {}
    executable = project_local_commands(
        {
            "xprompts": {
                "tool": {
                    "content": "hi",
                    "steps": [{"bash": "echo hi"}],
                }
            }
        },
        source="local",
    )
    assert executable.projection["macros"]["tool"]["steps"][0]["bash"] == "echo hi"
    assert "macros.tool" in executable.blocked_paths


def test_partial_override_of_executable_lower_is_command_bearing() -> None:
    """A prompt-only local edit to an executable lower macro still blocks."""
    lower = {"tool": {"content": "hi", "bash": "echo hi"}}
    sparse = project_local_commands(
        {"macros": {"tool": {"input": {"q": "word"}}}},
        lower_macros=lower,
        source="local",
    )
    assert "macros.tool" in sparse.blocked_paths
    prompt_only_lower = {"hello": "world"}
    benign = project_local_commands(
        {"macros": {"hello": {"input": {"q": "word"}}}},
        lower_macros=prompt_only_lower,
        source="local",
    )
    assert benign.projection == {}


def test_commit_hooks_whole_contribution_is_command_bearing() -> None:
    """Any local ``commit_hooks`` key blocks as a whole, auxiliaries included."""
    out = project_local_commands(
        {
            "commit_hooks": {
                "before": "",
                "after_rebase_timeout_seconds": 10,
            }
        },
        source="local",
    )
    assert out.projection["commit_hooks"]["after_rebase_timeout_seconds"] == 10
    assert "commit_hooks" in out.blocked_paths
    filtered = filter_trusted_local_layer(
        {
            "timezone": "UTC",
            "commit_hooks": {"before": "just fix"},
        },
        trusted=False,
    )
    assert filtered.effective_layer == {"timezone": "UTC"}
    assert "commit_hooks" in filtered.removed_paths


def test_file_hook_template_reference_is_command_bearing() -> None:
    """Template ``use:`` entries block even without a literal command."""
    out = project_local_commands(
        {"file_hooks": [{"use": "builtin@fmt", "name": "fmt"}]},
        source="local",
    )
    assert out.projection["file_hooks"][0]["use"] == "builtin@fmt"
    assert "file_hooks[0]" in out.blocked_paths
    literal = project_local_commands(
        {"file_hooks": [{"name": "run", "command": "echo hi"}]},
        source="local",
    )
    assert "file_hooks[0]" in literal.blocked_paths


def test_nested_workflow_steps_are_command_bearing() -> None:
    """Nested parallel bash steps and ``use:`` imports block conservatively."""
    parallel = project_local_commands(
        {
            "workflows": {
                "deploy": {
                    "steps": [
                        {
                            "name": "fan",
                            "parallel": [
                                {"name": "a", "agent": "review"},
                                {"name": "b", "bash": "echo hi"},
                            ],
                        }
                    ]
                }
            }
        },
        source="local",
    )
    assert "workflows.deploy" in parallel.blocked_paths
    reference = project_local_commands(
        {"workflows": {"tool": {"steps": [{"name": "s", "use": "steps@shared"}]}}},
        source="local",
    )
    assert "workflows.tool" in reference.blocked_paths
    prompt_only = project_local_commands(
        {"workflows": {"notes": {"steps": [{"name": "main", "prompt_part": "hello"}]}}},
        source="local",
    )
    assert prompt_only.projection == {}


def test_mapping_order_does_not_change_digest() -> None:
    """Canonical serialization sorts keys; YAML order/comments never matter."""
    first = project_local_commands(
        {"commit_hooks": {"before": "just fix", "after": "echo done"}},
        source="local",
    )
    second = project_local_commands(
        {"commit_hooks": {"after": "echo done", "before": "just fix"}},
        source="local",
    )
    assert first.digest == second.digest
    assert first.canonical_json == second.canonical_json
    assert len(first.digest) == 64
    expected = hashlib.sha256(
        (LOCAL_COMMAND_DIGEST_DOMAIN + first.canonical_json).encode()
    ).hexdigest()
    assert first.digest == expected
    assert json.loads(first.canonical_json) == first.projection


def test_digest_binding_matches_projection_digest() -> None:
    """Hashing the projected value directly reproduces the stored digest."""
    out = project_local_commands(
        {"commit_hooks": {"before": "just fix"}},
        source="local",
    )
    hashed = digest_local_commands(out.projection)
    assert hashed.digest == out.digest
    assert hashed.canonical_json == out.canonical_json


def test_filter_preserves_non_command_keys_and_prompt_macros() -> None:
    """Untrusted filtering keeps display config and prompt-only definitions."""
    out = filter_trusted_local_layer(
        {
            "timezone": "UTC",
            "commit_hooks": {"before": "just fix"},
            "file_hooks": [{"name": "run", "command": "echo hi"}],
            "macros": {
                "hello": "world",
                "tool": {"content": "hi", "bash": "echo hi"},
            },
        },
        trusted=False,
    )
    assert out.effective_layer == {
        "timezone": "UTC",
        "macros": {"hello": "world"},
    }
    assert out.status == "untrusted-filtered"
    trusted = filter_trusted_local_layer(
        {
            "timezone": "UTC",
            "commit_hooks": {"before": "just fix"},
        },
        trusted=True,
    )
    assert trusted.effective_layer["commit_hooks"]["before"] == "just fix"
    assert trusted.removed_paths == ()


def test_invalid_shapes_block_conservatively() -> None:
    """Ambiguous executable shapes fail closed instead of passing through."""
    bad_hooks = project_local_commands(
        {"file_hooks": {"name": "not-a-list"}},
        source="local",
    )
    assert "file_hooks" in bad_hooks.blocked_paths
    bad_macros = project_local_commands(
        {"macros": ["not-a-mapping"]},
        source="local",
    )
    assert "macros" in bad_macros.blocked_paths
    filtered = filter_trusted_local_layer(
        {"file_hooks": {"name": "not-a-list"}},
        trusted=False,
    )
    assert "file_hooks" not in filtered.effective_layer


def test_trust_decision_matches_current_digest_only() -> None:
    """Only a current acknowledged digest (and policy) counts as trusted."""
    out = project_local_commands(
        {"commit_hooks": {"before": "just fix"}},
        source="local",
    )
    assert decide_local_command_trust(out.digest, None).trusted is False
    assert decide_local_command_trust(out.digest, out.digest).trusted is True
    assert decide_local_command_trust("0" * 64, out.digest).trusted is False
    stale_policy = decide_local_command_trust(
        out.digest,
        out.digest,
        current_policy_version=LOCAL_COMMAND_TRUST_POLICY_VERSION,
        acknowledged_policy_version=LOCAL_COMMAND_TRUST_POLICY_VERSION + 1,
    )
    assert stale_policy.trusted is False
    assert stale_policy.reason == "policy-version-mismatch"

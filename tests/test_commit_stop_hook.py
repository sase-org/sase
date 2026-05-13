"""Tests for commit stop hook message and block behavior."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from sase.scripts.sase_commit_stop_hook import (
    _build_name_instruction,
    _build_commit_instruction_message,
    _emit_block,
    build_commit_details,
    native_marker_path,
)


def test_commit_instruction_non_pr_method_includes_scope_restriction() -> None:
    """Non-PR methods must constrain commit message scope to current commit."""
    message = _build_commit_instruction_message("/sase_git_commit", "create_commit")
    assert "The commit method type is `create_commit`." in message
    assert "describe only the changes in this commit" in message
    assert "Do NOT describe the entire pull request" in message


def test_commit_instruction_pr_method_omits_scope_restriction() -> None:
    """PR method should not include non-PR commit message scope constraints."""
    message = _build_commit_instruction_message(
        "/sase_git_commit", "create_pull_request"
    )
    assert "The commit method type is `create_pull_request`." in message
    assert "describe only the changes in this commit" not in message
    assert "Do NOT describe the entire pull request" not in message


def test_commit_instruction_unknown_method_defaults_to_scope_restriction() -> None:
    """Unknown methods should use non-PR scope guidance by default."""
    message = _build_commit_instruction_message("/sase_git_commit", "unexpected_method")
    assert "The commit method type is `unexpected_method`." in message
    assert "describe only the changes in this commit" in message
    assert "Do NOT describe the entire pull request" in message


@pytest.mark.parametrize(
    "method", ["create_commit", "create_proposal", "create_pull_request"]
)
def test_commit_instruction_includes_method_override_warning(method: str) -> None:
    """Instruction text must warn agents not to override the stated method."""
    message = _build_commit_instruction_message("/sase_git_commit", method)
    assert "Do NOT pass a --type value that conflicts" in message
    assert f"--type {method}" in message


def test_commit_instruction_includes_bead_close_when_bead_id_is_set() -> None:
    """SASE_BEAD_ID should close the bead before invoking the commit skill."""
    message = _build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "  sase-2d.4  "
    )
    assert "If you DID make these changes" in message
    assert message.index("sase bead close sase-2d.4") < message.index(
        "using your /sase_git_commit skill"
    )
    assert "using your /sase_git_commit skill" in message
    assert "sase bead close sase-2d.4" in message
    assert "verify bead `sase-2d.4` is closed" in message
    assert "before invoking the commit skill" in message


def test_commit_instruction_gates_bead_close_on_agent_ownership() -> None:
    """Bead closure must be explicit only for changes this agent made."""
    message = _build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "sase-2d.4"
    )
    ownership_gate = "If you DID make these changes"
    bead_close = "sase bead close sase-2d.4"
    assert (
        "First decide whether the listed uncommitted changes were made by you"
        in message
    )
    assert (
        "If you did NOT make these changes, ignore this warning for the session"
        in message
    )
    assert message.index(ownership_gate) < message.index(bead_close)


def test_commit_instruction_omits_bead_close_when_bead_id_is_unset() -> None:
    """Unset or blank bead IDs must not mention bead closure."""
    message = _build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "   "
    )
    assert "sase bead close" not in message
    assert "bead `" not in message


def test_pr_name_instruction_is_well_formed_for_missing_name(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SASE_COMMIT_METHOD", "create_pull_request")
    monkeypatch.delenv("SASE_PR_NAME", raising=False)
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", "/tmp/projects/sase.sase")

    message = _build_name_instruction()

    assert message is not None
    assert 'MUST include `"name": "<name>"`' in message
    assert "consist of lowercase letters and underscores" in message
    assert 'MUST start with "sase_"' in message
    assert 'consist" of' not in message


def test_codex_emit_block_includes_details_in_json(capsys: object) -> None:
    """Codex JSON reason must contain details when provided."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=True
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=False
        ),
    ):
        rc = _emit_block("generic reason", details="detailed instructions here")

    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[union-attr]
    payload = json.loads(captured.out.strip())
    assert payload["decision"] == "block"
    assert payload["reason"] == "detailed instructions here"
    assert "detailed instructions here" in captured.err


def test_codex_emit_block_falls_back_to_reason(capsys: object) -> None:
    """Codex JSON reason falls back to generic reason when details is None."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=True
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=False
        ),
    ):
        rc = _emit_block("generic reason")

    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[union-attr]
    payload = json.loads(captured.out.strip())
    assert payload["reason"] == "generic reason"
    assert captured.err == ""


def test_gemini_emit_block_includes_details_in_json(capsys: object) -> None:
    """Gemini JSON reason must contain details when provided."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=False
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=True
        ),
    ):
        rc = _emit_block("generic reason", details="detailed instructions here")

    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[union-attr]
    payload = json.loads(captured.out.strip())
    assert payload["decision"] == "deny"
    assert payload["reason"] == "detailed instructions here"


def test_native_marker_path_uses_sase_tmpdir(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """native_marker_path honors SASE_TMPDIR for the dedup marker location."""
    monkeypatch.setenv("SASE_TMPDIR", str(tmp_path))
    marker = native_marker_path("260511_120000")
    assert marker == tmp_path / "sase_commit_hook_done_260511_120000"


def test_build_commit_details_clean_returns_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When _get_changed_files reports clean, details are empty."""
    monkeypatch.setattr(
        "sase.scripts.sase_commit_stop_hook._get_changed_files",
        lambda _: (False, []),
    )
    has, files, instr, details = build_commit_details("/some/dir")
    assert has is False
    assert files == []
    assert instr == ""
    assert details == ""


def test_build_commit_details_matches_hook_message(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Public helper emits the exact instruction the hook would produce."""
    monkeypatch.setattr(
        "sase.scripts.sase_commit_stop_hook._get_changed_files",
        lambda _: (True, ["src/x.py", "src/y.py"]),
    )
    monkeypatch.setattr(
        "sase.scripts.sase_commit_stop_hook._resolve_commit_skill",
        lambda _: "/sase_git_commit",
    )
    monkeypatch.setenv("SASE_COMMIT_METHOD", "create_commit")
    monkeypatch.delenv("SASE_BEAD_ID", raising=False)
    monkeypatch.delenv("SASE_PR_NAME", raising=False)

    has, files, instr, details = build_commit_details("/some/dir")
    expected_instr = _build_commit_instruction_message(
        "/sase_git_commit", "create_commit", None
    )
    assert has is True
    assert files == ["src/x.py", "src/y.py"]
    assert instr == expected_instr
    assert details == (
        "Uncommitted changes detected:\nsrc/x.py\nsrc/y.py\n\n" + expected_instr
    )


def test_claude_emit_block_returns_nonzero_with_details(capsys: object) -> None:
    """Claude gets details on stderr with non-zero exit."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=False
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=False
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_qwen_runtime", return_value=False
        ),
    ):
        rc = _emit_block("generic reason", details="detailed instructions here")

    assert rc == 2
    captured = capsys.readouterr()  # type: ignore[union-attr]
    assert captured.out == ""
    assert "detailed instructions here" in captured.err


def test_qwen_emit_block_uses_deny_decision_like_gemini(capsys: object) -> None:
    """Qwen (a Gemini fork) must emit the same deny-shaped JSON payload."""
    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._is_codex_runtime", return_value=False
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._is_gemini_runtime", return_value=False
        ),
        patch("sase.scripts.sase_commit_stop_hook._is_qwen_runtime", return_value=True),
    ):
        rc = _emit_block("generic reason", details="detailed instructions here")

    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[union-attr]
    payload = json.loads(captured.out.strip())
    assert payload["decision"] == "deny"
    assert payload["reason"] == "detailed instructions here"


def test_qwen_runtime_detection_excludes_gemini(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Qwen Code exports both QWEN_PROJECT_DIR and GEMINI_PROJECT_DIR; the
    Gemini detector must yield to Qwen when both are present so the runtime
    is labeled and dispatched as qwen."""
    from sase.scripts.sase_commit_stop_hook import (
        _is_gemini_runtime,
        _is_qwen_runtime,
    )

    monkeypatch.setenv("QWEN_PROJECT_DIR", "/tmp")
    monkeypatch.setenv("GEMINI_PROJECT_DIR", "/tmp")
    assert _is_qwen_runtime() is True
    assert _is_gemini_runtime() is False


def test_resolve_project_dir_prefers_qwen_project_dir(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """_resolve_project_dir should consult QWEN_PROJECT_DIR."""
    from sase.scripts.sase_commit_stop_hook import _resolve_project_dir

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("GEMINI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.setenv("QWEN_PROJECT_DIR", str(tmp_path))
    assert _resolve_project_dir() == str(tmp_path)

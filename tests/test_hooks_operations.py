"""Tests for hook operations, state checking, and file updates."""

import os
import tempfile

from sase.ace.changespec import (
    HookEntry,
    HookStatusLine,
)
from sase.ace.hooks import (
    contract_test_target_command,
    get_hook_output_path,
    get_test_target_from_hook,
    has_failing_test_target_hooks,
    has_running_hooks,
    hook_needs_run,
    update_changespec_hooks_field,
)
from sase.ace.hooks.execution import (
    _format_hooks_field,
)
from sase.ace.hooks.test_targets import expand_test_target_shorthand
from sase.sase_utils import get_sase_directory


def _make_hook(
    command: str,
    commit_entry_num: str = "1",
    timestamp: str | None = None,
    status: str | None = None,
    duration: str | None = None,
) -> HookEntry:
    """Helper function to create a HookEntry with a status line."""
    if timestamp is None and status is None:
        return HookEntry(command=command)
    status_line = HookStatusLine(
        commit_entry_num=commit_entry_num,
        timestamp=timestamp or "",
        status=status or "",
        duration=duration,
    )
    return HookEntry(command=command, status_lines=[status_line])


# Tests for hook_needs_run
def test_hook_needs_run_no_history_entry() -> None:
    """Test that hook doesn't need run if no history entry number."""
    hook = HookEntry(command="flake8 src")
    # No history entry means no run needed
    assert hook_needs_run(hook, None) is False

    hook2 = _make_hook(
        command="flake8 src",
        commit_entry_num="1",
        timestamp="240601123456",
        status="PASSED",
    )
    assert hook_needs_run(hook2, None) is False  # No history entry


def test_hook_needs_run_up_to_date() -> None:
    """Test that hook doesn't need run if status line exists for current entry."""
    hook = _make_hook(
        command="flake8 src",
        commit_entry_num="1",
        timestamp="240601130000",
        status="PASSED",
    )
    assert hook_needs_run(hook, "1") is False  # Has status for entry 1


# Tests for test target hook functions
def test_get_test_target_from_hook_valid() -> None:
    """Test extracting test target from a valid test target hook."""
    hook = _make_hook(command="bb_rabbit_test //foo/bar:test1", status="PASSED")
    assert get_test_target_from_hook(hook) == "//foo/bar:test1"


def test_get_test_target_from_hook_with_spaces() -> None:
    """Test extracting test target from hook with extra spaces."""
    hook = _make_hook(command="bb_rabbit_test  //foo/bar:test1 ", status="PASSED")
    assert get_test_target_from_hook(hook) == "//foo/bar:test1"


def test_get_test_target_from_hook_not_test_target() -> None:
    """Test that non-test target hook returns None."""
    hook = _make_hook(command="flake8 src", status="PASSED")
    assert get_test_target_from_hook(hook) is None


# Tests for has_failing_test_target_hooks
def test_has_failing_test_target_hooks_none() -> None:
    """Test has_failing_test_target_hooks returns False for None input."""
    assert has_failing_test_target_hooks(None) is False


def test_has_failing_test_target_hooks_empty() -> None:
    """Test has_failing_test_target_hooks returns False for empty list."""
    assert has_failing_test_target_hooks([]) is False


# Tests for has_running_hooks
def test_has_running_hooks_none() -> None:
    """Test has_running_hooks returns False for None input."""
    assert has_running_hooks(None) is False


# Tests for get_hook_output_path
def test_get_hook_output_path_special_chars() -> None:
    """Test get_hook_output_path sanitizes special characters."""
    path = get_hook_output_path("my/feature-test", "240601_123456")
    hooks_dir = get_sase_directory("hooks")
    # Special chars should be replaced with underscore
    assert path == os.path.join(hooks_dir, "my_feature_test-240601_123456.txt")


# Tests for format_timestamp_display
# Tests for _format_hooks_field
def test_format_hooks_field_empty() -> None:
    """Test formatting empty hooks list."""
    result = _format_hooks_field([])
    assert result == []


def test_format_hooks_field_summarize_complete_with_empty_suffix() -> None:
    """Test that summarize_complete suffix_type preserves prefix even with empty suffix."""
    status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="240601_123456",
        status="FAILED",
        duration="30s",
        suffix="",  # Empty suffix
        suffix_type="summarize_complete",
        summary="Some test summary",
    )
    hooks = [HookEntry(command="pytest tests", status_lines=[status_line])]
    result = _format_hooks_field(hooks)
    result_str = "".join(result)
    # The % prefix should be preserved even with empty suffix
    assert "(% | Some test summary)" in result_str


def test_format_hooks_field_multiline_suffix_collapsed() -> None:
    """Test that multi-line suffix content is collapsed to a single line."""
    status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="240601_123456",
        status="FAILED",
        duration="30s",
        suffix="Line one\n\n**`CheckTests/0 failed`**",
        suffix_type="error",
    )
    hooks = [HookEntry(command="pytest tests", status_lines=[status_line])]
    result = _format_hooks_field(hooks)
    result_str = "".join(result)
    # Verify the output is a single line per status (no embedded newlines in suffix)
    for line in result_str.split("\n"):
        if "| (1)" in line:
            # The status line should contain the collapsed suffix
            assert "Line one" in line
            assert "CheckTests/0 failed" in line
            # No embedded newlines - the suffix should be on this single line
            break
    else:
        raise AssertionError("Status line not found in output")


def test_format_hooks_field_multiline_summary_collapsed() -> None:
    """Test that multi-line summary content is collapsed to a single line."""
    status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="240601_123456",
        status="FAILED",
        duration="30s",
        suffix="",
        suffix_type="metahook_complete",
        summary="Multi\nline\nsummary",
    )
    hooks = [HookEntry(command="pytest tests", status_lines=[status_line])]
    result = _format_hooks_field(hooks)
    result_str = "".join(result)
    for line in result_str.split("\n"):
        if "| (1)" in line:
            assert "Multi line summary" in line
            break
    else:
        raise AssertionError("Status line not found in output")


# Tests for _apply_hooks_update with corrupt content
def test_apply_hooks_update_skips_corrupt_lines() -> None:
    """Test that _apply_hooks_update skips corrupt/orphaned text in HOOKS section."""
    from sase.ace.hooks.execution import _apply_hooks_update

    # Simulate a file where multi-line suffixes left orphaned text
    lines = [
        "NAME: test_cl\n",
        "HOOKS:\n",
        "  old_command\n",
        "      | (1) [240601_100000] PASSED (1m0s)\n",
        "some orphaned text from a multi-line suffix\n",
        "\n",
        "**bold markdown leftover**\n",
        "STATUS: Ready\n",
    ]
    new_hooks = [
        _make_hook(
            command="new_command",
            timestamp="240601_123456",
            status="FAILED",
            duration="2m30s",
        ),
    ]
    result = _apply_hooks_update(lines, "test_cl", new_hooks)
    result_str = "".join(result)

    # Old hook and corrupt text should be gone
    assert "old_command" not in result_str
    assert "orphaned text" not in result_str
    assert "bold markdown leftover" not in result_str
    # New hook should be present
    assert "new_command" in result_str
    # STATUS field should be preserved
    assert "STATUS: Ready" in result_str


def test_apply_hooks_update_stops_at_field_header() -> None:
    """Test that _apply_hooks_update stops skipping at known field headers."""
    from sase.ace.hooks.execution import _apply_hooks_update

    lines = [
        "NAME: test_cl\n",
        "HOOKS:\n",
        "  old_command\n",
        "      | (1) [240601_100000] PASSED (1m0s)\n",
        "COMMITS:\n",
        "  (1) Some commit message\n",
    ]
    new_hooks = [
        _make_hook(
            command="new_command",
            timestamp="240601_123456",
            status="PASSED",
        ),
    ]
    result = _apply_hooks_update(lines, "test_cl", new_hooks)
    result_str = "".join(result)

    # COMMITS section should be fully preserved
    assert "COMMITS:" in result_str
    assert "Some commit message" in result_str
    assert "new_command" in result_str


# Tests for update_changespec_hooks_field
def test_update_changespec_hooks_field_clear_status() -> None:
    """Test clearing hook status (for rerun)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("""## ChangeSpec
NAME: test_cl
DESCRIPTION:
  Test description
STATUS: Ready
HOOKS:
  my_command
      | (1) [240601_100000] FAILED (1m0s)
""")
        f.flush()
        file_path = f.name

    try:
        # Clear hook status (simulating rerun) - no status lines
        new_hooks = [HookEntry(command="my_command")]
        success = update_changespec_hooks_field(file_path, "test_cl", new_hooks)
        assert success is True

        # Verify status was cleared
        with open(file_path) as f:
            content = f.read()
        assert "my_command" in content
        # Status line should be gone
        assert "[240601_100000]" not in content
        assert "FAILED" not in content
    finally:
        os.unlink(file_path)


# Tests for expand_test_target_shorthand
def test_expand_test_target_shorthand_basic() -> None:
    """Test expansion of basic shorthand syntax."""
    assert expand_test_target_shorthand("//foo:test") == "bb_rabbit_test //foo:test"
    assert (
        expand_test_target_shorthand("//bar:baz_test")
        == "bb_rabbit_test //bar:baz_test"
    )


def test_expand_test_target_shorthand_with_bang_prefix() -> None:
    """Test expansion with ! prefix."""
    assert expand_test_target_shorthand("!//foo:test") == "!bb_rabbit_test //foo:test"


def test_expand_test_target_shorthand_with_dollar_prefix() -> None:
    """Test expansion with $ prefix."""
    assert expand_test_target_shorthand("$//foo:test") == "$bb_rabbit_test //foo:test"


def test_expand_test_target_shorthand_with_combined_prefixes() -> None:
    """Test expansion with combined !$ prefixes."""
    assert expand_test_target_shorthand("!$//foo:test") == "!$bb_rabbit_test //foo:test"


def test_expand_test_target_shorthand_already_expanded() -> None:
    """Test that already expanded commands are unchanged."""
    assert (
        expand_test_target_shorthand("bb_rabbit_test //foo:test")
        == "bb_rabbit_test //foo:test"
    )


def test_expand_test_target_shorthand_non_test_command() -> None:
    """Test that non-test commands are unchanged."""
    assert expand_test_target_shorthand("some_other_command") == "some_other_command"
    assert expand_test_target_shorthand("flake8 src") == "flake8 src"


# Tests for contract_test_target_command
def test_contract_test_target_command_basic() -> None:
    """Test contraction of basic test target command."""
    assert contract_test_target_command("bb_rabbit_test //foo:test") == "//foo:test"
    assert (
        contract_test_target_command("bb_rabbit_test //bar:baz_test")
        == "//bar:baz_test"
    )


def test_contract_test_target_command_with_bang_prefix() -> None:
    """Test contraction with ! prefix."""
    assert contract_test_target_command("!bb_rabbit_test //foo:test") == "!//foo:test"


def test_contract_test_target_command_with_dollar_prefix() -> None:
    """Test contraction with $ prefix."""
    assert contract_test_target_command("$bb_rabbit_test //foo:test") == "$//foo:test"


def test_contract_test_target_command_with_combined_prefixes() -> None:
    """Test contraction with combined !$ prefixes."""
    assert contract_test_target_command("!$bb_rabbit_test //foo:test") == "!$//foo:test"


def test_contract_test_target_command_already_contracted() -> None:
    """Test that already contracted commands are unchanged."""
    assert contract_test_target_command("//foo:test") == "//foo:test"


def test_contract_test_target_command_non_double_slash_target() -> None:
    """Test that bb_rabbit_test without // target is not contracted."""
    # If target doesn't start with //, don't contract
    assert (
        contract_test_target_command("bb_rabbit_test some_target")
        == "bb_rabbit_test some_target"
    )


def test_contract_test_target_command_non_test_command() -> None:
    """Test that non-test commands are unchanged."""
    assert contract_test_target_command("some_other_command") == "some_other_command"
    assert contract_test_target_command("flake8 src") == "flake8 src"


# Tests for round-trip expansion and contraction
def test_expand_contract_roundtrip() -> None:
    """Test that expanding then contracting returns the original shorthand."""
    original = "//foo:test"
    expanded = expand_test_target_shorthand(original)
    contracted = contract_test_target_command(expanded)
    assert contracted == original


def test_expand_contract_roundtrip_with_prefix() -> None:
    """Test round-trip with ! prefix."""
    original = "!//foo:test"
    expanded = expand_test_target_shorthand(original)
    contracted = contract_test_target_command(expanded)
    assert contracted == original

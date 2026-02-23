"""Hook execution - background process management."""

import os
import subprocess
import tempfile

from sase.sase_utils import (
    generate_timestamp,
    strip_reverted_suffix,
)

from ..changespec import (
    ChangeSpec,
    HookEntry,
    HookStatusLine,
)
from .persistence import get_hook_output_path
from .timestamps import (
    calculate_duration_from_timestamps,
    format_duration,
    get_hook_file_age_seconds_from_timestamp,
)


def start_hook_background(
    changespec: ChangeSpec,
    hook: HookEntry,
    workspace_dir: str,
    history_entry_id: str,
) -> tuple[HookEntry, str]:
    """Start a hook command as a background process.

    The hook runs asynchronously. Use check_hook_completion() to check status.

    Args:
        changespec: The ChangeSpec the hook belongs to.
        hook: The hook entry to run.
        workspace_dir: The workspace directory to run the command in.
        history_entry_id: The COMMITS entry ID this hook run is associated with.

    Returns:
        Tuple of (updated HookEntry with RUNNING status, output_path).
    """
    timestamp = generate_timestamp()
    output_path = get_hook_output_path(changespec.name, timestamp)

    # Get the actual command to run (strips "!" prefix if present)
    actual_command = hook.run_command

    # Create wrapper script with retry logic for transient errors
    wrapper_script = f"""#!/bin/bash

# Retry configuration
MAX_RETRIES=3
RETRY_DELAY=60

# Patterns that trigger retry (grep -E format)
RETRIABLE_PATTERNS=(
    "Per user memory limit reached"
)

echo "=== HOOK COMMAND ==="
echo "{actual_command}"
echo "===================="
echo ""

# Build grep pattern from array
build_pattern() {{
    local IFS='|'
    echo "${{RETRIABLE_PATTERNS[*]}}"
}}

# Check if output contains retriable error
is_retriable() {{
    local output_file="$1"
    local pattern
    pattern=$(build_pattern)
    grep -qE "$pattern" "$output_file" 2>/dev/null
}}

# Execute command with retry logic
attempt=1
while [ $attempt -le $MAX_RETRIES ]; do
    tmp_output=$(mktemp)
    trap "rm -f '$tmp_output'" EXIT

    # Stream output in real-time while also capturing for retry inspection
    ( {actual_command} ) 2>&1 | tee "$tmp_output"
    exit_code=${{PIPESTATUS[0]}}  # Get command's exit code, not tee's

    if [ $exit_code -ne 0 ] && [ $attempt -lt $MAX_RETRIES ] && is_retriable "$tmp_output"; then
        echo ""
        echo "=== RETRY ATTEMPT $attempt/$MAX_RETRIES ==="
        echo "Detected retriable error (output shown above). Waiting ${{RETRY_DELAY}}s before retry..."
        echo ""
        echo "=== WAITING ${{RETRY_DELAY}}s ==="
        rm -f "$tmp_output"
        sleep $RETRY_DELAY
        attempt=$((attempt + 1))
    else
        if [ $attempt -gt 1 ]; then
            echo ""
            echo "=== FINAL ATTEMPT ($attempt/$MAX_RETRIES) COMPLETE ==="
        fi
        rm -f "$tmp_output"
        break
    fi
done

echo ""
# Log end timestamp in YYmmdd_HHMMSS format (America/New_York timezone)
end_timestamp=$(TZ="America/New_York" date +"%y%m%d_%H%M%S")
echo "===HOOK_COMPLETE=== END_TIMESTAMP: $end_timestamp EXIT_CODE: $exit_code"
# Ensure output is flushed to disk before exiting to prevent race condition
# where the parent process sees the process as dead but hasn't read the marker yet
sync
exit $exit_code
"""
    # Write wrapper script to temp file (don't delete - background process needs it)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False
    ) as wrapper_file:
        wrapper_file.write(wrapper_script)
        wrapper_path = wrapper_file.name

    os.chmod(wrapper_path, 0o755)

    # Start as background process and capture PID
    with open(output_path, "w") as output_file:
        process = subprocess.Popen(
            [wrapper_path],
            cwd=workspace_dir,
            stdout=output_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        process_pid = process.pid

    # Create new status line for this run
    # Use PID suffix with running_process type to get " - ($: PID)" marker
    new_status_line = HookStatusLine(
        commit_entry_num=history_entry_id,
        timestamp=timestamp,
        status="RUNNING",
        duration=None,
        suffix=str(process_pid),
        suffix_type="running_process",
    )

    # Preserve existing status lines and add the new one
    existing_status_lines = list(hook.status_lines) if hook.status_lines else []
    updated_hook = HookEntry(
        command=hook.command,
        status_lines=existing_status_lines + [new_status_line],
    )

    return updated_hook, output_path


def check_hook_completion(
    changespec: ChangeSpec,
    hook: HookEntry,
    target_status_line: HookStatusLine | None = None,
) -> HookEntry | None:
    """Check if a running hook has completed.

    Reads the hook's output file looking for the completion marker.
    Updates the RUNNING status line with completion status.

    Args:
        changespec: The ChangeSpec the hook belongs to.
        hook: The hook entry to check (must have a RUNNING status line).
        target_status_line: Optional specific status line to check. If provided,
            checks this status line's output file instead of the first RUNNING one.
            This is needed when multiple status lines are RUNNING for the same hook.

    Returns:
        Updated HookEntry with PASSED/FAILED status if complete, None if still running.
    """
    # Find the status line to check
    running_status_line = None
    running_idx = -1
    if target_status_line is not None:
        # Use the provided status line
        running_status_line = target_status_line
        if hook.status_lines:
            for idx, sl in enumerate(hook.status_lines):
                if sl is target_status_line:
                    running_idx = idx
                    break
    else:
        # Find the FIRST RUNNING status line (original behavior)
        if hook.status_lines:
            for idx, sl in enumerate(hook.status_lines):
                if sl.status == "RUNNING":
                    running_status_line = sl
                    running_idx = idx
                    break

    if running_status_line is None:
        return None

    output_path = get_hook_output_path(changespec.name, running_status_line.timestamp)

    # If the output file doesn't exist with the current name, try the original name
    if not os.path.exists(output_path):
        original_name = strip_reverted_suffix(changespec.name)
        if original_name != changespec.name:
            output_path = get_hook_output_path(
                original_name, running_status_line.timestamp
            )

    if not os.path.exists(output_path):
        return None

    try:
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    # Look for completion marker with end timestamp
    marker = "===HOOK_COMPLETE=== END_TIMESTAMP: "
    marker_pos = content.rfind(marker)

    if marker_pos == -1:
        return None

    # Parse completion line
    end_timestamp: str | None = None
    try:
        after_marker = content[marker_pos + len(marker) :].strip()
        parts = after_marker.split()
        end_timestamp = parts[0]
        exit_code = int(parts[2])
    except (ValueError, IndexError):
        exit_code = 1
        end_timestamp = None

    # Calculate duration
    if end_timestamp:
        duration_seconds = calculate_duration_from_timestamps(
            running_status_line.timestamp, end_timestamp
        )
        if duration_seconds is not None:
            duration = format_duration(duration_seconds)
        else:
            age = get_hook_file_age_seconds_from_timestamp(
                running_status_line.timestamp
            )
            duration = format_duration(age) if age is not None else "0s"
    else:
        age = get_hook_file_age_seconds_from_timestamp(running_status_line.timestamp)
        duration = format_duration(age) if age is not None else "0s"

    completed_status = "PASSED" if exit_code == 0 else "FAILED"

    # Auto-append summary suffix for hooks with "!" prefix (skip_fix_hook)
    # BUT only if no metahook matches - let metahook workflow handle those
    auto_skip_suffix = None
    if completed_status == "FAILED" and hook.skip_fix_hook:
        from sase.metahook_config import find_matching_metahook

        # Read hook output to check for metahook match
        hook_output_content = ""
        if os.path.exists(output_path):
            with open(output_path, encoding="utf-8") as f:
                hook_output_content = f.read()

        # Only auto-summarize if no metahook matches
        if not find_matching_metahook(hook.command, hook_output_content):
            from sase.summarize_utils import get_file_summary

            auto_skip_suffix = get_file_summary(
                target_file=output_path,
                usage="a hook failure suffix in a COMMITS entry",
                fallback="Hook Command Failed",
            )

    # Create updated status line
    updated_status_line = HookStatusLine(
        commit_entry_num=running_status_line.commit_entry_num,
        timestamp=running_status_line.timestamp,
        status=completed_status,
        duration=duration,
        suffix=auto_skip_suffix,
        suffix_type="error" if auto_skip_suffix else None,
    )

    # Replace the RUNNING status line with the completed one
    updated_status_lines = list(hook.status_lines) if hook.status_lines else []
    if running_idx >= 0:
        updated_status_lines[running_idx] = updated_status_line

    return HookEntry(
        command=hook.command,
        status_lines=updated_status_lines,
    )

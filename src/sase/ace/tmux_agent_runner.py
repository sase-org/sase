"""Tmux-based agent runner for the ace TUI.

When running inside tmux, this provides a more accurate end-to-end
representation by spawning the TUI in a real tmux pane and capturing
via `tmux capture-pane`.
"""

import json
import shutil
import subprocess
import sys
import time
import uuid
from typing import Literal

# Maps Textual key names to tmux send-keys format
TEXTUAL_TO_TMUX_KEYS: dict[str, str] = {
    "enter": "Enter",
    "escape": "Escape",
    "tab": "Tab",
    "space": "Space",
    "backspace": "BSpace",
    "delete": "DC",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "PPage",
    "pagedown": "NPage",
    "slash": "/",
    "question_mark": "?",
    "ctrl+a": "C-a",
    "ctrl+b": "C-b",
    "ctrl+c": "C-c",
    "ctrl+d": "C-d",
    "ctrl+e": "C-e",
    "ctrl+f": "C-f",
    "ctrl+g": "C-g",
    "ctrl+h": "C-h",
    "ctrl+k": "C-k",
    "ctrl+l": "C-l",
    "ctrl+n": "C-n",
    "ctrl+p": "C-p",
    "ctrl+r": "C-r",
    "ctrl+u": "C-u",
    "ctrl+w": "C-w",
}


def _map_key(textual_key: str) -> str:
    """Map a Textual key name to tmux send-keys format.

    Single characters pass through directly. Named keys are looked up
    in TEXTUAL_TO_TMUX_KEYS.

    Raises:
        ValueError: If the key is not a single character and has no mapping.
    """
    if len(textual_key) == 1:
        return textual_key
    if textual_key in TEXTUAL_TO_TMUX_KEYS:
        return TEXTUAL_TO_TMUX_KEYS[textual_key]
    raise ValueError(f"Unknown Textual key: {textual_key!r}")


def _capture_pane(session_name: str) -> str:
    """Capture the contents of a tmux pane."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", session_name],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _wait_for_stable_content(
    session_name: str,
    timeout: float = 10.0,
    poll_interval: float = 0.2,
) -> str:
    """Poll capture-pane until two consecutive captures are identical and non-empty.

    Returns the last captured content, even on timeout.
    """
    deadline = time.monotonic() + timeout
    prev = ""
    while time.monotonic() < deadline:
        current = _capture_pane(session_name)
        if current and current == prev:
            return current
        prev = current
        time.sleep(poll_interval)
    return prev


def run_tmux_agent_mode(
    query: str,
    keys: list[str] | None = None,
    size: tuple[int, int] = (120, 40),
    model_tier_override: Literal["large", "small"] | None = None,
) -> str:
    """Run the ace TUI in a real tmux session and capture the screen.

    Args:
        query: Query string for filtering ChangeSpecs.
        keys: Optional list of Textual key names to send.
        size: Terminal size as (width, height).
        model_tier_override: Override model tier for LLM providers.

    Returns:
        JSON string with keys: screen, state, error.
    """
    session_name = f"sase-agent-{uuid.uuid4().hex[:8]}"
    w, h = size

    # Build the inner command
    sase_cmd = shutil.which("sase") or f"{sys.executable} -m sase"
    inner_cmd = f"{sase_cmd} ace {query!r}"
    if model_tier_override:
        inner_cmd += f" --model-tier {model_tier_override}"

    try:
        # Create detached tmux session
        subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session_name,
                "-x",
                str(w),
                "-y",
                str(h),
                inner_cmd,
            ],
            check=True,
        )

        # Wait for TUI to render
        _wait_for_stable_content(session_name)

        # Send keys
        if keys:
            for key in keys:
                tmux_key = _map_key(key)
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, tmux_key],
                    check=True,
                )

            # Wait for TUI to settle after key input
            _wait_for_stable_content(session_name)

        # Final capture
        screen = _capture_pane(session_name)
        return json.dumps({"screen": screen, "state": {}, "error": None})

    except Exception as e:
        return json.dumps({"screen": "", "state": {}, "error": str(e)})

    finally:
        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            check=False,
        )

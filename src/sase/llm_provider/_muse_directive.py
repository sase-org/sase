"""Single-turn directive and wait-guard helpers for the Muse provider.

The prompt prefix lives here because Muse has no append-system-prompt flag.
:mod:`sase.llm_provider.muse_provider` imports the public names below; no
``_``-prefixed name is imported across modules.
"""

from __future__ import annotations

import os

# Synchronous-execution ceiling for the legacy ``shell`` tool
# (``muse exec --enable-shell-tool``). Muse kills any command still running
# past this point and discards all of its output, so anything that can
# outlast it must go to a SASE monitor, chosen before the command starts.
MUSE_SYNC_CEILING_SECONDS = 600
_MUSE_SYNC_CEILING_MINUTES = MUSE_SYNC_CEILING_SECONDS // 60
# Wrap commands of uncertain length so a slow run still leaves evidence with
# a minute of headroom before the kill.
_MUSE_SYNC_COMMAND_TIMEOUT_SECONDS = MUSE_SYNC_CEILING_SECONDS - 60
MUSE_ENABLE_SHELL_TOOL_ARG = "--enable-shell-tool"

_MUSE_MAX_WAIT_CONTINUATIONS_ENV = "SASE_MUSE_MAX_WAIT_CONTINUATIONS"
_DEFAULT_MUSE_MAX_WAIT_CONTINUATIONS = 2
MUSE_WAIT_CONTINUATION_NUDGE = (
    "Your previous reply ended the turn claiming to wait for a command, "
    "notification, or wake-up. This SASE session is single-turn: nothing "
    "will wake you, and nothing you started is still running. Finish now. "
    "Rerun anything unfinished in the foreground, or hand a genuinely long "
    "command to `/sase_monitor` with `--next`. Then submit your final "
    "declaration and give your final answer. If your work was already "
    "complete, restate your final answer without claiming to wait."
)


def muse_max_wait_continuations() -> int:
    """Return the bounded stranded-wait continuation budget."""
    raw_value = os.environ.get(_MUSE_MAX_WAIT_CONTINUATIONS_ENV)
    if raw_value is None:
        return _DEFAULT_MUSE_MAX_WAIT_CONTINUATIONS
    try:
        return max(0, int(raw_value))
    except ValueError:
        return _DEFAULT_MUSE_MAX_WAIT_CONTINUATIONS


def muse_synchronous_shell_enabled() -> bool:
    """Return whether Muse runs commands in the legacy synchronous ``shell`` tool.

    Falls back to the registry default (on) when the flag cannot be resolved,
    so a broken flag snapshot fails closed toward no post-turn wake.
    """
    try:
        from sase.feature_flags import FeatureFlag, current_flags
        from sase.feature_flags.models import FeatureFlagError

        return current_flags().enabled(FeatureFlag.muse_synchronous_shell)
    except FeatureFlagError:
        return True


def _muse_single_turn_directive(*, synchronous: bool) -> str:
    """Return the mode-aware single-turn prompt prefix for Muse."""
    if synchronous:
        tool_sentence = (
            "Your `shell` tool runs each command synchronously but kills any "
            f"command still running after {_MUSE_SYNC_CEILING_MINUTES} minutes "
            "and discards all of its output, so blocking for up to about "
            f"{_MUSE_SYNC_COMMAND_TIMEOUT_SECONDS // 60} minutes is expected "
            "and correct."
        )
    else:
        tool_sentence = "Your `bash` tool may move a long command to the background."
    if synchronous:
        inline_rule = "Run everything else inline."
    else:
        inline_rule = (
            "Run everything else inline, and read each backgrounded command's "
            "result before finishing."
        )
    if synchronous:
        wait_rule = "Never end your turn to wait."
    else:
        wait_rule = (
            "Never submit your final declaration or end your turn while a "
            "command you started is still running. SASE stops the Muse "
            "process about two minutes after your final declaration, killing "
            "anything still running."
        )
    return (
        "SASE single-turn instructions for Muse Code: this session is exactly "
        "one turn, and nothing can wake you after you end it. "
        f"{tool_sentence} Decide where a command runs before you start it: "
        "(1) Final verification: prefer prepared monitor completion "
        '(`/sase_final`, "Prepared Monitor Completion"). Run '
        "`sase final prepare` with your finished manifest (`bead_action: "
        "close` when the bead is done), then `sase monitor start -p verify -f "
        "<ref> -- <verification command>` (`just check` in SASE repos). "
        "Passing work lands with no further turn. (2) Commands that can take "
        f"longer than {_MUSE_SYNC_CEILING_MINUTES} minutes go to "
        "`/sase_monitor` with `--next` before you start them. Examples: full "
        "builds and installs, full test or visual suites, `just check-full`, "
        "CI, deploy, release, or rate-limit waits. The project's memory names "
        "its known-long commands. Combine dependent steps into one monitored "
        "command. `sase tool run` is the exception: it returns before your "
        "ceiling on its own, so never wrap it in `timeout` and never route it "
        "to a monitor up front. If it prints an escalation block, run the "
        "printed `sase monitor start -J ...` command next. "
        f"(3) {inline_rule} Wrap an unrecorded command of uncertain length "
        "that is not `sase tool run` as "
        f"`timeout {_MUSE_SYNC_COMMAND_TIMEOUT_SECONDS} <cmd> > "
        '<log> 2>&1; echo "exit=$?"; tail -n 80 <log>` so a slow run still '
        "leaves evidence. `sase tool run` output is retained; replay it with "
        "`sase tool show RUN -l`. Never background or detach a command (`&`, "
        "`nohup`, `setsid`). Never use cron, workflow, subagent, or snooze "
        "tools to wait. Never cancel or rerun an in-flight command to move it "
        f"to a monitor. {wait_rule}"
    )


def wrap_muse_prompt(prompt: str, *, synchronous: bool) -> str:
    """Prefix *prompt* with the mode-aware single-turn directive.

    Muse has no append-system-prompt flag, so the directive travels as a
    prompt prefix the way ``agy.py`` wraps its print-mode prompt.
    """
    directive = _muse_single_turn_directive(synchronous=synchronous)
    return f"{directive}\n\n--- User Prompt ---\n{prompt}"


__all__ = [
    "MUSE_ENABLE_SHELL_TOOL_ARG",
    "MUSE_SYNC_CEILING_SECONDS",
    "MUSE_WAIT_CONTINUATION_NUDGE",
    "muse_max_wait_continuations",
    "muse_synchronous_shell_enabled",
    "wrap_muse_prompt",
]

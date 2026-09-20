"""Notification delivery rule checks for ``sase doctor``."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.sound_playback import expand_sound_path, resolve_sound_player
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.notifications.delivery import configured_notification_rules

_RESERVED_SOUNDS = frozenset({"bell", "none"})


def check_config_notification_rules() -> DiagnosticCheck:
    """Flag ``ace.notification_rules`` entries that are dropped or cannot work."""
    try:
        configured = configured_notification_rules()
    except Exception as exc:
        return DiagnosticCheck(
            id="config.notification_rules",
            group="config",
            status="WARN",
            title="Notification delivery rules",
            summary="could not read the config layers to check notification rules",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Run `sase doctor -C config.layers` to find the failing layer.",
            ),
            data={"rule_count": 0, "ignored_count": 0, "problem_count": 0},
        )

    problems: list[str] = []
    ignored_count = 0
    sound_files: list[str] = []
    for entry in configured:
        where = f"{entry.layer}: {entry.label}"
        if entry.rule is None:
            ignored_count += 1
            problems.extend(
                f"{where}: {problem} (rule ignored)" for problem in entry.problems
            )
            continue
        problems.extend(f"{where}: {problem}" for problem in _rule_problems(entry.rule))
        sound = entry.rule.get("sound")
        if isinstance(sound, str) and _is_sound_file(sound):
            sound_files.append(sound)
            path = expand_sound_path(sound)
            if not path.is_file():
                problems.append(f"{where}: sound file {str(path)!r} does not exist")
    if sound_files and resolve_sound_player() is None:
        problems.append(
            f"no audio player found on PATH for {len(sound_files)} configured sound "
            "file(s); they will stay silent (macOS needs afplay; Linux needs paplay, "
            "aplay, or ffplay)"
        )

    status: CheckStatus = "WARN" if problems else "OK"
    applied = len(configured) - ignored_count
    summary = (
        f"{len(problems)} notification rule problem(s) found"
        if problems
        else f"{applied} notification rule(s) configured"
        if configured
        else "no notification rules configured"
    )
    return DiagnosticCheck(
        id="config.notification_rules",
        group="config",
        status=status,
        title="Notification delivery rules",
        summary=summary,
        details=tuple(problems)[:MAX_DETAIL_ROWS],
        next_steps=(
            (
                "Fix the reported `ace.notification_rules` entries, then run "
                "`sase notify rules` to see the merged list and "
                "`sase notify rules -e <notification-id>` to see which rule "
                "decides a notification.",
            )
            if problems
            else ()
        ),
        data={
            "rule_count": len(configured),
            "ignored_count": ignored_count,
            "problem_count": len(problems),
            "problems": problems,
        },
    )


def _is_sound_file(sound: str) -> bool:
    """Return whether ``sound`` names a file rather than a reserved word or nothing."""
    return bool(sound.strip()) and sound.lower() not in _RESERVED_SOUNDS


def _rule_problems(rule: dict[str, Any]) -> list[str]:
    """Return the problems of a rule that is applied but may not do what was meant."""
    problems: list[str] = []
    sound = rule.get("sound")
    sets_sound = isinstance(sound, str) and bool(sound.strip())
    if "toast" not in rule and not sets_sound:
        problems.append(
            "sets neither toast nor sound, so it never changes a delivery"
            + (" (a blank sound sets nothing)" if sound is not None else "")
        )
    match = rule.get("match")
    if isinstance(match, dict):
        for criterion, value in match.items():
            patterns = [value] if isinstance(value, str) else value
            if not patterns:
                problems.append(
                    f"match.{criterion} is an empty list, which matches nothing"
                )
            problems.extend(
                f"match.{criterion} pattern {pattern!r} has an unclosed '[', "
                "which matches a literal '['"
                for pattern in patterns
                if _has_unclosed_bracket(pattern)
            )
    return problems


def _has_unclosed_bracket(pattern: str) -> bool:
    """Return whether a ``[`` in the glob never closes (the core matches it literally)."""
    index = 0
    while index < len(pattern):
        if pattern[index] != "[":
            index += 1
            continue
        start = index + 1
        if pattern[start : start + 1] == "!":
            start += 1
        if pattern[start : start + 1] == "]":
            start += 1  # a leading ``]`` is a class member, not the terminator
        end = pattern.find("]", start)
        if end == -1:
            return True
        index = end + 1
    return False

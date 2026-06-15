"""CLI handler for ``sase skill use``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.agent.identity import AgentIdentityError, require_agent_identity
from sase.skills.use_log import (
    SkillUseError,
    append_skill_use_event,
    build_skill_use_event,
    normalize_skill_name,
    normalize_skill_reason,
)


def handle_skills_use_command(args: argparse.Namespace) -> None:
    """Append one audited skill-use event for the current agent."""
    try:
        skill_name = normalize_skill_name(args.name)
        reason = normalize_skill_reason(args.reason)
        agent = require_agent_identity(purpose="skill use logs")
        event = build_skill_use_event(
            skill_name,
            reason=reason,
            agent=agent,
            cwd=Path.cwd(),
        )
        append_skill_use_event(event)
    except (AgentIdentityError, SkillUseError, OSError, UnicodeError) as exc:
        print(f"sase skill use: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Logged skill use: {skill_name}")

"""Hook data models."""

from dataclasses import dataclass

from .stitches import parse_stitch_id


@dataclass(init=False)
class HookStatusLine:
    """Represents a single hook status line.

    Format in file:
      (N) [YYmmdd_HHMMSS] RUNNING/PASSED/FAILED/KILLED (XmYs) - (SUFFIX)
      (N) [YYmmdd_HHMMSS] RUNNING/PASSED/FAILED/KILLED (XmYs) - (!: MSG)
      (N) [YYmmdd_HHMMSS] RUNNING/PASSED/FAILED/KILLED (XmYs) - (SUFFIX | SUMMARY)
    Where N is the stitch-history entry ID.

    The optional suffix can be:
    - A timestamp (YYmmdd_HHMMSS) indicating a fix-hook agent is running
    - "Hook Command Failed" indicating no fix-hook hints should be shown
    - "ZOMBIE" indicating a stale fix-hook agent (>2h old timestamp)

    Compound suffix format uses " | " delimiter:
    - (@: fix_hook-<PID>-<timestamp> | <summary>) - fix-hook running with summary
    - (<proposal_id> | <summary>) - fix-hook succeeded with proposal
    - (!: fix-hook Failed | <summary>) - fix-hook failed with summary
    - (%: <summary>) - summarize complete, ready for fix-hook

    Suffix type markers:
    - "!:" = error
    - "@:" = running_agent
    - "~@:" = killed_agent
    - "$:" = running_process
    - "?$:" = pending_dead_process
    - "~$:" = killed_process
    - "%:" = summarize_complete

    Note: The suffix stores just the message (e.g., "ZOMBIE"), and the
    prefix is added when formatting for display/storage.
    """

    stitch_id: str  # The STITCHES/COMMITS entry ID (e.g., "1", "1a", "2")
    timestamp: str  # YYmmdd_HHMMSS format
    status: str  # RUNNING, PASSED, FAILED, KILLED
    duration: str | None = None  # e.g., "1m23s"
    suffix: str | None = None  # e.g., "YYmmdd_HHMMSS", "KILLED", "Hook Command Failed"
    suffix_type: str | None = None  # See "Suffix type markers" above
    summary: str | None = None  # Summary from summarize_hook workflow (compound suffix)

    def __init__(
        self,
        commit_entry_num: str | None = None,
        timestamp: str = "",
        status: str = "",
        duration: str | None = None,
        suffix: str | None = None,
        suffix_type: str | None = None,
        summary: str | None = None,
        *,
        stitch_id: str | None = None,
    ) -> None:
        if commit_entry_num is not None and stitch_id is not None:
            if commit_entry_num != stitch_id:
                raise ValueError(
                    "HookStatusLine received conflicting commit_entry_num and stitch_id"
                )
        resolved_id = commit_entry_num if commit_entry_num is not None else stitch_id
        if resolved_id is None:
            raise TypeError(
                "HookStatusLine missing required argument: 'stitch_id' "
                "(legacy: 'commit_entry_num')"
            )
        self.stitch_id = resolved_id
        self.timestamp = timestamp
        self.status = status
        self.duration = duration
        self.suffix = suffix
        self.suffix_type = suffix_type
        self.summary = summary

    @property
    def commit_entry_num(self) -> str:
        """Legacy compatibility alias for :attr:`stitch_id`."""
        return self.stitch_id

    @commit_entry_num.setter
    def commit_entry_num(self, value: str) -> None:
        self.stitch_id = value


@dataclass
class HookEntry:
    """Represents a single hook command entry in the HOOKS field.

    Format in file:
      some_command
        (1) [YYmmdd_HHMMSS] PASSED (1m23s)
        (2) [YYmmdd_HHMMSS] RUNNING

    Each hook can have multiple status lines, one per stitch-history entry.

    Command prefixes:
    - "!" prefix: FAILED status lines auto-append "- (!: Hook Command Failed)"
      to skip fix-hook hints. Also excluded from mentor eligibility.
    - "$" prefix: Hook is NOT run for proposed stitch entries (e.g., "1a").
      Also marks hook as "unlimited" (not subject to --max-runners limit).

    Prefixes can be combined as "!$" (e.g., "!$sase_hg_presubmit").
    All prefixes are stripped when displaying or running the command.
    """

    command: str
    status_lines: list[HookStatusLine] | None = None

    def _get_prefix(self) -> str:
        """Extract the prefix portion (any combination of '!' and '$')."""
        prefix = ""
        for char in self.command:
            if char in "!$":
                prefix += char
            else:
                break
        return prefix

    @property
    def skip_fix_hook(self) -> bool:
        """Check if '!' prefix is present (skip fix-hook on failure)."""
        return "!" in self._get_prefix()

    @property
    def skip_proposal_runs(self) -> bool:
        """Check if '$' prefix is present (skip for proposal entries)."""
        return "$" in self._get_prefix()

    @property
    def is_unlimited(self) -> bool:
        """Check if '$' prefix is present (not subject to runner limits)."""
        return "$" in self._get_prefix()

    @property
    def display_command(self) -> str:
        """Get the command for display purposes (strips leading '!' and '$')."""
        return self.command.lstrip("!$")

    @property
    def run_command(self) -> str:
        """Get the command to actually run (strips leading '!' and '$')."""
        return self.command.lstrip("!$")

    @property
    def latest_status_line(self) -> HookStatusLine | None:
        """Get the most recent status line (highest stitch ID)."""
        if not self.status_lines:
            return None
        return max(
            self.status_lines,
            key=lambda sl: parse_stitch_id(sl.stitch_id),
        )

    def get_status_line_for_stitch(self, stitch_id: str) -> HookStatusLine | None:
        """Get status line for a specific stitch ID (e.g., '1', '1a')."""
        if not self.status_lines:
            return None
        for sl in self.status_lines:
            if sl.stitch_id == stitch_id:
                return sl
        return None

    def get_status_line_for_commit_entry(
        self, commit_entry_id: str
    ) -> HookStatusLine | None:
        """Legacy alias for :meth:`get_status_line_for_stitch`."""
        return self.get_status_line_for_stitch(commit_entry_id)

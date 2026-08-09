"""Mentor data models."""

from dataclasses import dataclass


@dataclass
class MentorStatusLine:
    """Represents a single mentor status line.

    Format in file:
      | [YYmmdd_HHMMSS] <profile>:<mentor> - RUNNING - (@: mentor_<name>-<PID>-YYmmdd_HHMMSS)
      | [YYmmdd_HHMMSS] <profile>:<mentor> - PASSED - (XhYmZs)
      | [YYmmdd_HHMMSS] <profile>:<mentor> - COMMENTED - (XhYmZs)
      | [YYmmdd_HHMMSS] <profile>:<mentor> - FAILED - (XhYmZs)

    The timestamp prefix links to the chat file at ~/.sase/chats/*.md.

    When RUNNING:
      - suffix format: mentor_<name>-<PID>-YYmmdd_HHMMSS
      - suffix_type: "running_agent"

    When complete (PASSED/COMMENTED/FAILED):
      - suffix format: duration (e.g., "0h2m15s")
      - suffix_type: "plain" or None
      - COMMENTED = mentor produced one or more review comments
      - PASSED = mentor found no issues

    Suffix type markers:
    - "@:" = running_agent
    - "!:" = error
    """

    profile_name: str  # The mentor profile name
    mentor_name: str  # The mentor name within the profile
    status: str  # RUNNING, PASSED, FAILED, COMMENTED
    timestamp: str | None  # YYmmdd_HHMMSS format, for linking to chat files
    duration: str | None = None  # e.g., "0h2m15s" when complete
    suffix: str | None = (
        None  # e.g., "mentor_complete-12345-251230_151429" when running
    )
    suffix_type: str | None = None  # "running_agent", "plain", "error"


@dataclass(init=False)
class MentorEntry:
    """Represents a single entry in the MENTORS field.

    Format in file:
      (<id>) <profile1> [<profile2> ...]
          | <profile>:<mentor> - RUNNING - (@: mentor_<name>-<PID>-YYmmdd_HHMMSS)
          | <profile>:<mentor> - PASSED - (XhYmZs)

    Where <id> matches a stitch-history entry ID (e.g., "1", "2").
    Multiple profiles can be listed if they all matched for this entry.
    Each profile+mentor combination has its own status line.
    """

    stitch_id: str  # Matches STITCHES/COMMITS entry ID (e.g., "1", "2")
    profiles: list[str]  # Profile names that were triggered for this entry
    status_lines: list[MentorStatusLine] | None = None
    is_draft: bool = False  # True if entry was created during Draft status

    def __init__(
        self,
        entry_id: str | None = None,
        profiles: list[str] | None = None,
        status_lines: list[MentorStatusLine] | None = None,
        is_draft: bool = False,
        *,
        stitch_id: str | None = None,
    ) -> None:
        if entry_id is not None and stitch_id is not None:
            if entry_id != stitch_id:
                raise ValueError(
                    "MentorEntry received conflicting entry_id and stitch_id"
                )
        resolved_id = entry_id if entry_id is not None else stitch_id
        if resolved_id is None:
            raise TypeError(
                "MentorEntry missing required argument: 'stitch_id' "
                "(legacy: 'entry_id')"
            )
        self.stitch_id = resolved_id
        self.profiles = profiles if profiles is not None else []
        self.status_lines = status_lines
        self.is_draft = is_draft

    @property
    def entry_id(self) -> str:
        """Legacy compatibility alias for :attr:`stitch_id`."""
        return self.stitch_id

    @entry_id.setter
    def entry_id(self, value: str) -> None:
        self.stitch_id = value

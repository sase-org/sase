"""Mentor output schema, storage, and acceptance state tracking."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SASE_MENTORS_DIR = Path.home() / ".sase" / "mentors"

# ── Dataclasses ──────────────────────────────────────────────────────────


@dataclass
class MentorComment:
    """A single review comment produced by a mentor."""

    focus_name: str
    file_path: str
    line_number: int
    description: str
    severity: str  # "error" | "warning" | "suggestion"


@dataclass
class MentorOutput:
    """Structured output from a mentor review run."""

    mentor_name: str
    profile_name: str
    role: str
    comments: list[MentorComment]


# ── JSON Schema ──────────────────────────────────────────────────────────

MENTOR_OUTPUT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "mentor_name": {"type": "string"},
        "profile_name": {"type": "string"},
        "role": {"type": "string"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "focus_name": {"type": "string"},
                    "file_path": {"type": "string"},
                    "line_number": {"type": "integer"},
                    "description": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["error", "warning", "suggestion"],
                    },
                },
                "required": [
                    "focus_name",
                    "file_path",
                    "line_number",
                    "description",
                    "severity",
                ],
            },
        },
    },
    "required": ["mentor_name", "profile_name", "role", "comments"],
}


# ── Save / Load mentor outputs ───────────────────────────────────────────


def save_mentor_output(
    cl_name: str,
    profile_name: str,
    mentor_name: str,
    timestamp: str,
    output: MentorOutput,
) -> Path:
    """Save mentor output to disk as JSON.

    File is written to ``~/.sase/mentors/<cl>-<profile>-<mentor>-<ts>.json``.

    Returns:
        Path to the saved file.
    """
    SASE_MENTORS_DIR.mkdir(parents=True, exist_ok=True)
    safe_cl = cl_name.replace("/", "_")
    filename = f"{safe_cl}-{profile_name}-{mentor_name}-{timestamp}.json"
    path = SASE_MENTORS_DIR / filename
    path.write_text(json.dumps(asdict(output), indent=2), encoding="utf-8")
    return path


def _load_mentor_output(path: Path) -> MentorOutput:
    """Load a single mentor output from a JSON file.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    comments = [MentorComment(**c) for c in data["comments"]]
    return MentorOutput(
        mentor_name=data["mentor_name"],
        profile_name=data["profile_name"],
        role=data["role"],
        comments=comments,
    )


def _load_all_mentor_outputs(cl_name: str) -> list[tuple[Path, MentorOutput]]:
    """Load all mentor outputs for a given CL.

    Returns:
        List of (path, MentorOutput) tuples sorted by filename (timestamp order).
    """
    if not SASE_MENTORS_DIR.is_dir():
        return []
    safe_cl = cl_name.replace("/", "_")
    results: list[tuple[Path, MentorOutput]] = []
    for path in sorted(SASE_MENTORS_DIR.glob(f"{safe_cl}-*.json")):
        # Skip acceptance state files
        if path.name.endswith("-acceptance.json"):
            continue
        if path.name.endswith("-files.json"):
            continue
        try:
            results.append((path, _load_mentor_output(path)))
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("Skipping malformed mentor output: %s", path)
    return results


def save_file_snapshots(
    cl_name: str,
    profile_name: str,
    mentor_name: str,
    timestamp: str,
    revision: str,
    files: dict[str, str],
) -> Path:
    """Save file content snapshots alongside mentor output.

    File is written to ``~/.sase/mentors/<cl>-<profile>-<mentor>-<ts>-files.json``.
    """
    SASE_MENTORS_DIR.mkdir(parents=True, exist_ok=True)
    safe_cl = cl_name.replace("/", "_")
    filename = f"{safe_cl}-{profile_name}-{mentor_name}-{timestamp}-files.json"
    path = SASE_MENTORS_DIR / filename
    data = {"revision": revision, "files": files}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def load_file_snapshots(
    cl_name: str,
    profile_name: str,
    mentor_name: str,
    timestamp: str,
) -> dict[str, str]:
    """Load file snapshots for a mentor output.

    Returns an empty dict if the file doesn't exist or is malformed.
    """
    safe_cl = cl_name.replace("/", "_")
    filename = f"{safe_cl}-{profile_name}-{mentor_name}-{timestamp}-files.json"
    path = SASE_MENTORS_DIR / filename
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("files", {})
    except (json.JSONDecodeError, TypeError, AttributeError):
        log.warning("Malformed file snapshots: %s", path)
        return {}


def load_mentor_outputs_for_commit(
    cl_name: str, timestamps: set[str]
) -> list[tuple[Path, MentorOutput]]:
    """Load mentor outputs matching specific timestamps.

    Each mentor output file is named ``<cl>-<profile>-<mentor>-<timestamp>.json``.
    The *timestamps* set (from ``MentorStatusLine.timestamp``) is matched against
    the final segment of each filename.

    Returns:
        List of (path, MentorOutput) tuples for the matching timestamps.
    """
    all_outputs = _load_all_mentor_outputs(cl_name)
    return [
        (p, o)
        for p, o in all_outputs
        if any(p.stem.endswith(f"-{ts}") for ts in timestamps)
    ]


# ── Acceptance state ─────────────────────────────────────────────────────


@dataclass
class MentorAcceptanceState:
    """Tracks which mentor comments have been accepted.

    Maps ``(profile_name, mentor_name, comment_index)`` to ``bool``.
    """

    accepted: dict[str, bool] = field(default_factory=dict)

    @staticmethod
    def _key(profile_name: str, mentor_name: str, comment_index: int) -> str:
        return f"{profile_name}:{mentor_name}:{comment_index}"

    def is_accepted(
        self, profile_name: str, mentor_name: str, comment_index: int
    ) -> bool:
        """Check if a comment is accepted."""
        return self.accepted.get(
            self._key(profile_name, mentor_name, comment_index), False
        )

    def set_accepted(
        self,
        profile_name: str,
        mentor_name: str,
        comment_index: int,
        value: bool,
    ) -> None:
        """Set acceptance state for a comment."""
        self.accepted[self._key(profile_name, mentor_name, comment_index)] = value

    def toggle(self, profile_name: str, mentor_name: str, comment_index: int) -> bool:
        """Toggle acceptance and return new state."""
        key = self._key(profile_name, mentor_name, comment_index)
        new_value = not self.accepted.get(key, False)
        self.accepted[key] = new_value
        return new_value

    @property
    def accepted_count(self) -> int:
        """Return total number of accepted comments."""
        return sum(1 for v in self.accepted.values() if v)

    @property
    def total_count(self) -> int:
        """Return total number of tracked comments."""
        return len(self.accepted)


def save_acceptance_state(
    cl_name: str, entry_id: str, state: MentorAcceptanceState
) -> Path:
    """Save acceptance state to disk.

    File is written to ``~/.sase/mentors/<cl>-<entry_id>-acceptance.json``.
    """
    SASE_MENTORS_DIR.mkdir(parents=True, exist_ok=True)
    safe_cl = cl_name.replace("/", "_")
    filename = f"{safe_cl}-{entry_id}-acceptance.json"
    path = SASE_MENTORS_DIR / filename
    path.write_text(json.dumps(state.accepted, indent=2), encoding="utf-8")
    return path


def load_acceptance_state(cl_name: str, entry_id: str) -> MentorAcceptanceState:
    """Load acceptance state from disk.

    Returns a fresh ``MentorAcceptanceState`` if the file does not exist.
    """
    safe_cl = cl_name.replace("/", "_")
    filename = f"{safe_cl}-{entry_id}-acceptance.json"
    path = SASE_MENTORS_DIR / filename
    if not path.is_file():
        return MentorAcceptanceState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return MentorAcceptanceState(accepted=data)
    except (json.JSONDecodeError, TypeError):
        log.warning("Malformed acceptance state: %s", path)
        return MentorAcceptanceState()

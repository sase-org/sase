"""Mentor configuration loading and validation."""

import logging
from dataclasses import dataclass
from pathlib import Path

from sase.config.core import load_merged_config

logger = logging.getLogger(__name__)


@dataclass
class _MentorFocusArea:
    """Represents a single focus area for a mentor's review."""

    focus_name: str
    description: str


@dataclass
class MentorConfig:
    """Represents a mentor configuration."""

    mentor_name: str
    role: str
    focus_areas: list[_MentorFocusArea]


@dataclass
class MentorProfileConfig:
    """Represents a mentor profile configuration.

    A mentor profile defines which mentors to run based on matching criteria.
    At least one of file_globs, diff_regexes, or amend_note_regexes must be provided.
    """

    profile_name: str
    mentors: list[MentorConfig]  # Inline mentor definitions
    file_globs: list[str] | None = None  # Glob patterns to match changed file paths
    diff_regexes: list[str] | None = None  # Regex patterns to match diff content
    amend_note_regexes: list[str] | None = None  # Regex patterns to match commit notes
    first_commit: bool = False  # Whether to match on the first commit of a ChangeSpec
    projects: list[str] | None = None  # Only match changespecs in these projects

    def __post_init__(self) -> None:
        """Validate that at least one matching criterion is provided."""
        if not (
            self.file_globs
            or self.diff_regexes
            or self.amend_note_regexes
            or self.first_commit
        ):
            raise ValueError(
                f"MentorProfile '{self.profile_name}' must have at least one of: "
                "file_globs, diff_regexes, amend_note_regexes, or first_commit"
            )


def _get_local_profile_names() -> set[str]:
    """Return the set of mentor profile names defined in the local sase.yml."""
    local_path = Path.cwd() / "sase.yml"
    if not local_path.is_file():
        return set()
    import yaml  # type: ignore[import-untyped]

    text = local_path.read_text(encoding="utf-8")
    local_data = yaml.safe_load(text)
    if not isinstance(local_data, dict):
        return set()
    names: set[str] = set()
    for item in local_data.get("mentor_profiles", []):
        if isinstance(item, dict) and "profile_name" in item:
            names.add(item["profile_name"])
    return names


def _load_mentor_profiles() -> list[MentorProfileConfig]:
    """Load all mentor profile configurations from the config file.

    Returns:
        List of MentorProfileConfig objects.

    Raises:
        FileNotFoundError: If config data is empty (no config files exist).
        ValueError: If config file is malformed.
    """
    data = load_merged_config()

    if not data:
        raise FileNotFoundError("Config file not found: ~/.config/sase/sase.yml")

    if not isinstance(data, dict):
        raise ValueError("Config must be a dictionary")

    # mentor_profiles is optional - return empty list if not present
    if "mentor_profiles" not in data:
        return []

    # Detect local profile names and CWD project for auto-scoping
    local_profile_names = _get_local_profile_names()
    detected_project: str | None = None
    if local_profile_names:
        from sase.xprompt.loader import detect_project

        detected_project = detect_project()

    profiles = []
    for item in data["mentor_profiles"]:
        if not isinstance(item, dict):
            raise ValueError("Each mentor profile must be a dictionary")
        if "profile_name" not in item or "mentors" not in item:
            raise ValueError(
                "Each mentor profile must have 'profile_name' and 'mentors' fields"
            )
        if not isinstance(item["mentors"], list):
            raise ValueError("'mentors' field must be a list")

        # Parse mentors as MentorConfig objects
        mentors = []
        for mentor_item in item["mentors"]:
            if not isinstance(mentor_item, dict):
                raise ValueError(
                    f"Each mentor in profile '{item['profile_name']}' must be a dictionary"
                )

            # Detect old format and give a clear error
            if "prompt" in mentor_item:
                raise ValueError(
                    f"Mentor in profile '{item['profile_name']}' uses the old "
                    "'prompt' format which is no longer supported. "
                    "Use 'mentor_name', 'role', and 'focus_areas' instead."
                )

            if "mentor_name" not in mentor_item:
                raise ValueError(
                    f"Each mentor in profile '{item['profile_name']}' must have "
                    "'mentor_name' field"
                )
            if "role" not in mentor_item:
                raise ValueError(
                    f"Each mentor in profile '{item['profile_name']}' must have "
                    "'role' field"
                )
            if "focus_areas" not in mentor_item:
                raise ValueError(
                    f"Each mentor in profile '{item['profile_name']}' must have "
                    "'focus_areas' field"
                )
            if not isinstance(mentor_item["focus_areas"], list):
                raise ValueError(
                    f"'focus_areas' field in mentor '{mentor_item['mentor_name']}' "
                    f"of profile '{item['profile_name']}' must be a list"
                )

            focus_areas = []
            for fa_item in mentor_item["focus_areas"]:
                if not isinstance(fa_item, dict):
                    raise ValueError(
                        f"Each focus area in mentor '{mentor_item['mentor_name']}' "
                        f"of profile '{item['profile_name']}' must be a dictionary"
                    )
                if "focus_name" not in fa_item or "description" not in fa_item:
                    raise ValueError(
                        f"Each focus area in mentor '{mentor_item['mentor_name']}' "
                        f"of profile '{item['profile_name']}' must have "
                        "'focus_name' and 'description' fields"
                    )
                focus_areas.append(
                    _MentorFocusArea(
                        focus_name=fa_item["focus_name"],
                        description=fa_item["description"],
                    )
                )

            mentors.append(
                MentorConfig(
                    mentor_name=mentor_item["mentor_name"],
                    role=mentor_item["role"],
                    focus_areas=focus_areas,
                )
            )

        # Determine projects scope: explicit YAML > auto-tag for local profiles
        explicit_projects = item.get("projects")
        if explicit_projects is not None:
            projects = explicit_projects
        elif (
            item["profile_name"] in local_profile_names and detected_project is not None
        ):
            projects = [detected_project]
        else:
            projects = None

        profiles.append(
            MentorProfileConfig(
                profile_name=item["profile_name"],
                mentors=mentors,
                file_globs=item.get("file_globs"),
                diff_regexes=item.get("diff_regexes"),
                amend_note_regexes=item.get("amend_note_regexes"),
                first_commit=item.get("first_commit", False),
                projects=projects,
            )
        )

    return profiles


def get_all_mentor_profiles() -> list[MentorProfileConfig]:
    """Get all mentor profile configurations.

    Returns:
        List of MentorProfileConfig objects, or empty list if config cannot be loaded.
    """
    try:
        return _load_mentor_profiles()
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Failed to load mentor profiles: %s", exc)
        return []


def get_mentor_profile_by_name(name: str) -> MentorProfileConfig | None:
    """Get a mentor profile configuration by name.

    Args:
        name: The name of the profile to find.

    Returns:
        The MentorProfileConfig if found, None otherwise.
    """
    for profile in get_all_mentor_profiles():
        if profile.profile_name == name:
            return profile
    return None


def get_mentor_from_profile(
    profile: MentorProfileConfig, mentor_name: str
) -> MentorConfig | None:
    """Get a mentor by name from a specific profile.

    Args:
        profile: The profile to search in.
        mentor_name: The name of the mentor to find.

    Returns:
        The MentorConfig if found, None otherwise.
    """
    for mentor in profile.mentors:
        if mentor.mentor_name == mentor_name:
            return mentor
    return None

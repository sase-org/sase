"""Generate random adjective-noun branch names for new workspaces."""

import random
import subprocess


_ADJECTIVES: tuple[str, ...] = (
    "able",
    "apt",
    "bare",
    "bold",
    "brave",
    "brief",
    "bright",
    "broad",
    "busy",
    "calm",
    "cheap",
    "chief",
    "civil",
    "clean",
    "clear",
    "close",
    "cold",
    "cool",
    "crisp",
    "crude",
    "dark",
    "dear",
    "deep",
    "dense",
    "dim",
    "dry",
    "dual",
    "dull",
    "eager",
    "even",
    "fair",
    "fast",
    "fine",
    "firm",
    "flat",
    "fond",
    "free",
    "fresh",
    "full",
    "glad",
    "grand",
    "grave",
    "green",
    "grim",
    "handy",
    "happy",
    "harsh",
    "huge",
    "humble",
    "ideal",
    "keen",
    "kind",
    "large",
    "lean",
    "light",
    "lively",
    "lone",
    "loud",
    "lucky",
    "mild",
    "modern",
    "moist",
    "narrow",
    "neat",
    "noble",
    "odd",
    "pale",
    "plain",
    "plump",
    "polite",
    "proud",
    "quick",
    "quiet",
    "rapid",
    "raw",
    "rich",
    "rigid",
    "rough",
    "royal",
    "safe",
)

_NOUNS: tuple[str, ...] = (
    "acorn",
    "anvil",
    "arch",
    "badge",
    "basin",
    "beam",
    "bell",
    "birch",
    "blade",
    "bloom",
    "bolt",
    "bone",
    "booth",
    "braid",
    "brick",
    "brook",
    "brush",
    "cairn",
    "cape",
    "cedar",
    "chalk",
    "chime",
    "clasp",
    "cliff",
    "cloak",
    "coal",
    "coin",
    "cord",
    "cove",
    "crane",
    "crest",
    "crown",
    "cube",
    "dew",
    "dock",
    "dome",
    "drift",
    "drum",
    "dune",
    "dust",
    "elm",
    "ember",
    "fawn",
    "fern",
    "fig",
    "finch",
    "flare",
    "flint",
    "forge",
    "frost",
    "gale",
    "gate",
    "gem",
    "glen",
    "globe",
    "gorge",
    "grain",
    "grove",
    "haven",
    "hawk",
    "helm",
    "hive",
    "horn",
    "isle",
    "jade",
    "knoll",
    "lake",
    "lark",
    "ledge",
    "maple",
    "marsh",
    "mesa",
    "mist",
    "moss",
    "nest",
    "oak",
    "opal",
    "peak",
    "pine",
    "pond",
)


def _get_existing_branch_names(workspace_dir: str) -> set[str]:
    """Get all existing branch names (local and remote) in the workspace."""
    result = subprocess.run(
        ["git", "branch", "-a"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    names: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "HEAD ->" in line:
            continue
        # Strip leading "* " from the current branch marker
        if line.startswith("* "):
            line = line[2:]
        # Strip "remotes/origin/" prefix from remote tracking branches
        if line.startswith("remotes/origin/"):
            line = line[len("remotes/origin/") :]
        names.add(line)
    return names


def _add_numeric_suffix(base_name: str, existing: set[str]) -> str:
    """Add a numeric suffix (-2, -3, ...) to make the name unique."""
    n = 2
    while True:
        candidate = f"{base_name}-{n}"
        if candidate not in existing:
            return candidate
        n += 1


# pyvision: xprompts/git.yml
# pyvision: xprompts/gh.yml
def generate_branch_name(workspace_dir: str) -> str:
    """Generate a random adjective-noun branch name that is not already taken."""
    existing = _get_existing_branch_names(workspace_dir)
    last_candidate = ""
    for _ in range(10):
        adj = random.choice(_ADJECTIVES)
        noun = random.choice(_NOUNS)
        last_candidate = f"{adj}-{noun}"
        if last_candidate not in existing:
            return last_candidate
    # All 10 attempts collided; fall back to numeric suffix on the last pick
    return _add_numeric_suffix(last_candidate, existing)

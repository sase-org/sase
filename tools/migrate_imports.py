#!/usr/bin/env python3
"""Migration script: rewrite imports and rename gai -> sase references.

Processes all .py files under src/sase/ in two passes:
  Pass 1: Rewrite imports from bare modules to sase.* package imports
  Pass 2: Rename gai-specific identifiers, paths, env vars, etc.
"""

import re
import sys
from pathlib import Path

SASE_ROOT = Path(__file__).resolve().parent.parent / "src" / "sase"

# All known top-level modules that were migrated into src/sase/
KNOWN_MODULES = {
    "ace",
    "axe",
    "accept_workflow",
    "commit_utils",
    "commit_workflow",
    "gemini_wrapper",
    "llm_provider",
    "main",
    "rewind_workflow",
    "status_state_machine",
    "vcs_provider",
    "xprompt",
    "shared_utils",
    "running_field",
    "rich_utils",
    "chat_history",
    "command_history",
    "change_actions",
    "amend_workflow",
    "workflow_base",
    "workflow_utils",
    "split_spec",
    "snippet_config",
    "hook_history",
    "prompt_history",
    "renumber_utils",
    "mentor_config",
    "mentor_workflow",
    "metahook_config",
    "summarize_utils",
    "summarize_workflow",
    "crs_workflow",
    "fix_hook_workflow",
    "axe_config",
    "axe_crs_runner",
    "axe_fix_hook_runner",
    "axe_mentor_runner",
    "axe_run_agent_runner",
    "axe_run_workflow_runner",
    "axe_runner_utils",
    "axe_summarize_hook_runner",
    "loop_crs_runner",
    "loop_fix_hook_runner",
    "loop_mentor_runner",
    "loop_run_agent_runner",
    "loop_runner_utils",
    "loop_summarize_hook_runner",
    "sase_utils",
    "sase_migrate_gp_to_yaml",
}

# Modules that were renamed during copy
RENAMED_MODULES = {
    "gai_utils": "sase_utils",
    "gai_migrate_gp_to_yaml": "sase_migrate_gp_to_yaml",
}


def rewrite_imports(content: str) -> str:
    """Pass 1: Rewrite bare module imports to sase.* package imports."""
    lines = content.split("\n")
    result = []

    for line in lines:
        new_line = _rewrite_import_line(line)
        result.append(new_line)

    return "\n".join(result)


def _rewrite_import_line(line: str) -> str:
    """Rewrite a single import line."""
    stripped = line.lstrip()

    # Skip relative imports
    if stripped.startswith("from ."):
        return line

    # Handle "from gai_utils import X" -> "from sase.sase_utils import X"
    # Handle "from gai_migrate_gp_to_yaml import X" -> "from sase.sase_migrate_gp_to_yaml import X"
    for old_name, new_name in RENAMED_MODULES.items():
        m = re.match(
            rf"^(\s*)from\s+{re.escape(old_name)}(\.\w+)*\s+import\s+", line
        )
        if m:
            indent = m.group(1)
            subpath = m.group(2) or ""
            rest = line[m.end() :]
            # Get everything after "import "
            import_part = line.split("import", 1)[1]
            return f"{indent}from sase.{new_name}{subpath} import{import_part}"

    # Handle "from <known_module> import X" -> "from sase.<known_module> import X"
    # Also handles "from <known_module>.sub import X"
    m = re.match(r"^(\s*)from\s+(\w+)((?:\.\w+)*)\s+import\s+", line)
    if m:
        indent = m.group(1)
        module = m.group(2)
        subpath = m.group(3) or ""
        if module in KNOWN_MODULES:
            import_part = line.split("import", 1)[1]
            return f"{indent}from sase.{module}{subpath} import{import_part}"

    # Handle "import gai_utils" -> "import sase.sase_utils"
    for old_name, new_name in RENAMED_MODULES.items():
        m = re.match(rf"^(\s*)import\s+{re.escape(old_name)}\s*$", line)
        if m:
            return f"{m.group(1)}import sase.{new_name}"
        # Handle "import gai_utils as gu"
        m = re.match(
            rf"^(\s*)import\s+{re.escape(old_name)}\s+as\s+(\w+)\s*$", line
        )
        if m:
            return f"{m.group(1)}import sase.{new_name} as {m.group(2)}"

    # Handle "import <known_module>" -> "import sase.<known_module>"
    m = re.match(r"^(\s*)import\s+(\w+)\s*$", line)
    if m:
        module = m.group(2)
        if module in KNOWN_MODULES:
            return f"{m.group(1)}import sase.{module}"

    # Handle "import <known_module> as X"
    m = re.match(r"^(\s*)import\s+(\w+)\s+as\s+(\w+)\s*$", line)
    if m:
        module = m.group(2)
        if module in KNOWN_MODULES:
            return f"{m.group(1)}import sase.{module} as {m.group(3)}"

    return line


# --- Pass 2: Content renaming ---

# Ordered list of (pattern, replacement) for content renaming.
# More specific patterns first to avoid partial matches.
CONTENT_RENAMES = [
    # Functions
    (r"\bget_gai_directory\b", "get_sase_directory"),
    (r"\bensure_gai_directory\b", "ensure_sase_directory"),
    (r"\b_ensure_gai_git_repo\b", "_ensure_sase_git_repo"),
    (r"\bget_gai_log_file\b", "get_sase_log_file"),
    (r"\binitialize_gai_log\b", "initialize_sase_log"),
    (r"\bfinalize_gai_log\b", "finalize_sase_log"),
    (r"\bget_gai_package_xprompts_dir\b", "get_sase_package_xprompts_dir"),
    # Variables
    (r"\bGAI_DIR\b", "SASE_DIR"),
    (r"\bbb_gai_context_dir\b", "bb_sase_context_dir"),
    # Env vars with GAI_ prefix (but not matching the above)
    (r"\bGAI_", "SASE_"),
    # Config paths
    (r"/\.gai/", "/.sase/"),
    (r"/\.config/gai/", "/.config/sase/"),
    (r"\bgai\.yml\b", "sase.yml"),
    (r"\bgai\.schema\.json\b", "sase.schema.json"),
    # Temp prefixes
    (r"\bgai_ace_", "sase_ace_"),
    (r"\bgai_commit_", "sase_commit_"),
    (r"\bgai_prompt_", "sase_prompt_"),
    (r"\bgai_reword_", "sase_reword_"),
    (r"\bgai_metahook_", "sase_metahook_"),
    # CLI prog
    (r'prog="gai"', 'prog="sase"'),
    # CLI command references (in strings)
    (r'"gai run"', '"sase run"'),
    (r'"gai ace"', '"sase ace"'),
    (r'"gai axe"', '"sase axe"'),
    (r'"gai commit"', '"sase commit"'),
    (r'"gai accept"', '"sase accept"'),
    (r'"gai rewind"', '"sase rewind"'),
    (r'"gai amend"', '"sase amend"'),
    (r'"gai status"', '"sase status"'),
    (r'"gai split"', '"sase split"'),
    (r'"gai renumber"', '"sase renumber"'),
    (r'"gai mentor"', '"sase mentor"'),
    (r'"gai metahook"', '"sase metahook"'),
    (r'"gai summarize"', '"sase summarize"'),
    (r'"gai fix-hook"', '"sase fix-hook"'),
    (r'"gai crs"', '"sase crs"'),
    (r'"gai migrate-gp-to-yaml"', '"sase migrate-gp-to-yaml"'),
    # Also handle single-quoted CLI refs
    (r"'gai run'", "'sase run'"),
    (r"'gai ace'", "'sase ace'"),
    (r"'gai axe'", "'sase axe'"),
    (r"'gai commit'", "'sase commit'"),
    (r"'gai accept'", "'sase accept'"),
    (r"'gai rewind'", "'sase rewind'"),
    (r"'gai amend'", "'sase amend'"),
    (r"'gai status'", "'sase status'"),
    (r"'gai split'", "'sase split'"),
    (r"'gai renumber'", "'sase renumber'"),
    (r"'gai mentor'", "'sase mentor'"),
    (r"'gai metahook'", "'sase metahook'"),
    (r"'gai summarize'", "'sase summarize'"),
    (r"'gai fix-hook'", "'sase fix-hook'"),
    (r"'gai crs'", "'sase crs'"),
    (r"'gai migrate-gp-to-yaml'", "'sase migrate-gp-to-yaml'"),
    # Commands
    (r"\bgai_get_workspace\b", "sase_get_workspace"),
    (r"\bgai_rewind\b", "sase_rewind"),
    # Generic word-boundary gai -> sase (catches docstrings, comments, remaining references)
    # This MUST be last to avoid interfering with more specific patterns
    (r"\bgai\b", "sase"),
    (r"\bGai\b", "Sase"),
]


def rename_content(content: str) -> str:
    """Pass 2: Rename gai references using word-boundary-safe regex."""
    for pattern, replacement in CONTENT_RENAMES:
        content = re.sub(pattern, replacement, content)
    return content


def process_file(filepath: Path) -> bool:
    """Process a single .py file. Returns True if modified."""
    original = filepath.read_text()

    # Pass 1: Import rewriting
    modified = rewrite_imports(original)

    # Pass 2: Content renaming
    modified = rename_content(modified)

    if modified != original:
        filepath.write_text(modified)
        return True
    return False


def main() -> None:
    """Process all .py files under src/sase/."""
    py_files = sorted(SASE_ROOT.rglob("*.py"))
    modified_count = 0
    total = len(py_files)

    for filepath in py_files:
        # Skip __init__.py at the sase root (it has the version)
        if filepath == SASE_ROOT / "__init__.py":
            continue
        # Skip __main__.py at the sase root
        if filepath == SASE_ROOT / "__main__.py":
            continue

        if process_file(filepath):
            modified_count += 1
            print(f"  Modified: {filepath.relative_to(SASE_ROOT.parent.parent)}")

    print(f"\nProcessed {total} files, modified {modified_count}")


if __name__ == "__main__":
    main()

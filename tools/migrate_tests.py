#!/usr/bin/env python3
"""Migrate test files from ~/lib/gai/test/ into tests/.

Copies all .py files, applies import rewriting (Pass 1), content renaming
(Pass 2), and patch-target rewriting (Pass 3) from migrate_imports.py.
"""

import re
import shutil
import sys
from pathlib import Path

# Add tools/ to path so we can import migrate_imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrate_imports import (
    KNOWN_MODULES,
    RENAMED_MODULES,
    rename_content,
    rewrite_imports,
)

SRC_DIR = Path.home() / "lib" / "gai" / "test"
DST_DIR = Path(__file__).resolve().parent.parent / "tests"

# Build set of all module prefixes that need sase. prepended in patch targets.
# This includes both KNOWN_MODULES and the OLD names from RENAMED_MODULES.
PATCH_MODULES = KNOWN_MODULES | set(RENAMED_MODULES.keys())


def rewrite_patch_targets(content: str) -> str:
    """Pass 3: Rewrite mock.patch() string targets to include sase. prefix.

    Handles patterns like:
        @patch("ace.hooks.func")         -> @patch("sase.ace.hooks.func")
        @patch("mentor_config.func")     -> @patch("sase.mentor_config.func")
        mock.patch("ace.foo.bar")        -> mock.patch("sase.ace.foo.bar")
        patch("gai_utils.func")          -> patch("sase.sase_utils.func")

    Only rewrites targets whose first dotted component is a KNOWN_MODULE
    or a RENAMED_MODULE key, and that are NOT already prefixed with 'sase.'.
    """
    # Build alternation pattern for all module names
    mod_pattern = "|".join(re.escape(m) for m in sorted(PATCH_MODULES, key=len, reverse=True))

    # Match patch/mock.patch string arguments (both single and double quotes)
    # Captures: the prefix up to the opening quote, the module target, and the rest
    pattern = re.compile(
        r"""((?:@?(?:mock\.)?patch(?:\.dict)?)\s*\(\s*)(["'])("""
        + mod_pattern
        + r""")(\.[^"']*)(["'])"""
    )

    def _replace(m: re.Match[str]) -> str:
        prefix = m.group(1)      # e.g. '@patch(' or 'mock.patch('
        open_q = m.group(2)      # opening quote
        module = m.group(3)      # e.g. 'ace' or 'mentor_config'
        rest = m.group(4)        # e.g. '.hooks.func'
        close_q = m.group(5)     # closing quote

        # Apply renamed modules (gai_utils -> sase_utils)
        if module in RENAMED_MODULES:
            module = RENAMED_MODULES[module]

        return f"{prefix}{open_q}sase.{module}{rest}{close_q}"

    return pattern.sub(_replace, content)


def remove_sys_path_hacks(content: str) -> str:
    """Remove sys.path.insert lines from conftest.py."""
    lines = content.split("\n")
    result = []
    skip_blank_after = False
    for line in lines:
        stripped = line.strip()
        # Skip sys.path.insert lines
        if stripped.startswith("sys.path.insert("):
            skip_blank_after = True
            continue
        # Skip the comment about adding to path
        if "Add src and test directories to path" in stripped:
            skip_blank_after = True
            continue
        # Skip the NOTE comment about importing before gai modules
        if "NOTE: This must happen BEFORE importing any" in stripped:
            skip_blank_after = True
            continue
        # Skip blank lines that immediately follow removed lines
        if skip_blank_after and stripped == "":
            skip_blank_after = False
            continue
        skip_blank_after = False
        result.append(line)
    return "\n".join(result)


def process_test_file(filepath: Path, is_conftest: bool = False) -> None:
    """Apply all migration passes to a single test file."""
    content = filepath.read_text()

    # Pass 1: Rewrite imports
    content = rewrite_imports(content)

    # Pass 2: Content renaming (gai -> sase identifiers)
    content = rename_content(content)

    # Pass 3: Rewrite patch targets
    content = rewrite_patch_targets(content)

    # Special handling for conftest.py: remove sys.path hacks
    if is_conftest:
        content = remove_sys_path_hacks(content)
        # Remove 'import sys' if sys is no longer used
        if "sys." not in content and "sys," not in content:
            lines = content.split("\n")
            content = "\n".join(
                line for line in lines if line.strip() != "import sys"
            )

    filepath.write_text(content)


def main() -> None:
    """Copy and migrate test files."""
    if not SRC_DIR.exists():
        print(f"ERROR: Source directory not found: {SRC_DIR}")
        sys.exit(1)

    DST_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all .py files (skip __pycache__)
    src_files = sorted(SRC_DIR.glob("*.py"))
    print(f"Found {len(src_files)} .py files in {SRC_DIR}")

    copied = 0
    for src_file in src_files:
        # Determine destination name
        dst_name = src_file.name
        if dst_name == "test_gai_utils.py":
            dst_name = "test_sase_utils.py"

        dst_file = DST_DIR / dst_name

        # Skip __init__.py (we create our own)
        if dst_name == "__init__.py":
            continue

        # Copy file
        shutil.copy2(src_file, dst_file)
        copied += 1

        # Process the file
        is_conftest = dst_name == "conftest.py"
        process_test_file(dst_file, is_conftest=is_conftest)
        print(f"  Migrated: {dst_name}")

    print(f"\nCopied and migrated {copied} test files to {DST_DIR}")


if __name__ == "__main__":
    main()

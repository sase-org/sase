# Loose Files in `src/sase/` — Audit & Grouping Recommendations

## File Inventory

There are 10 loose `.py` files in `src/sase/`. Two are standard Python packaging boilerplate; the remaining 8 are the
focus of this analysis.

### Standard files (not utilities)

| File          | Purpose                                                            |
| ------------- | ------------------------------------------------------------------ |
| `__init__.py` | Package init — version string, pydantic warning filter             |
| `__main__.py` | `python -m sase` entry point — delegates to `sase.main.entry:main` |

### The 8 files in question

| File                       | Lines | Importers | Summary                                                                                                                                                                                                                    |
| -------------------------- | ----- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent_launcher.py`        | 335   | 5         | Spawns background agent subprocesses. Two entry points: low-level `spawn_agent_subprocess` (used by TUI) and high-level `launch_agent_from_cwd` (used by `sase run --daemon` and xprompt chops).                           |
| `agent_names.py`           | 632   | 6         | Agent name resolution and lifecycle: find/kill/claim named agents, auto-generate alphabetic names (`a, b, ..., z, aa, ...`), list running agents.                                                                          |
| `multi_prompt.py`          | 110   | 10        | Parses user prompts into frontmatter + `---`-separated segments for multi-agent launch. Pure parsing, no I/O.                                                                                                              |
| `multi_prompt_launcher.py` | 275   | 6         | Orchestrates sequential launch of multi-prompt segments, with naming-wait between launches so `%wait` can auto-resolve.                                                                                                    |
| `rich_utils.py`            | 230   | 23        | Rich library wrappers for CLI output: status messages, panels, tables, live timers (`gemini_timer`).                                                                                                                       |
| `sase_utils.py`            | 300   | **89**    | Grab-bag of core utilities: timezone, tmpdir, vendored tools, shell commands, timestamps, `~/.sase/` directory management, ChangeSpec naming/branching, path shortening, hook prefix stripping, workspace command running. |
| `sdd.py`                   | 352   | 7         | Structured Design Document utilities: write spec/plan files, manage version-controlled or local SDD git repos, initialize beads, expand prompts for spec storage.                                                          |
| `shared_utils.py`          | 316   | 28        | Workflow/artifacts utilities: YAML dumping, artifacts directory creation, workflow init/finalize, log management, section marker handling, timestamp conversion, content helpers.                                          |

## Are they all shared utilities?

**No.** They fall into distinct categories:

### Actual shared utilities (used broadly across the codebase)

- **`sase_utils.py`** (89 importers) — Core low-level utilities. Genuinely shared.
- **`shared_utils.py`** (28 importers) — Workflow/artifacts helpers. Broadly used but more domain-specific than the name
  implies.
- **`rich_utils.py`** (23 importers) — CLI formatting. Genuinely shared.

### Domain-specific modules (agent lifecycle)

- **`agent_launcher.py`** — Agent subprocess spawning.
- **`agent_names.py`** — Agent naming and discovery.
- **`multi_prompt.py`** — Multi-prompt parsing.
- **`multi_prompt_launcher.py`** — Multi-prompt launch orchestration.

These four files form a cohesive domain: agent lifecycle management. They are consumed by `axe/` (execution engine),
`ace/` (TUI), and `main/` (CLI), but they are not generic utilities.

### Domain-specific module (planning/SDD)

- **`sdd.py`** — SDD file management and bead initialization. Tightly coupled to `sase.bead`, `sase.llm_provider`, and
  `sase.gemini_wrapper`.

## Key problems

1. **`sase_utils.py` is a God module.** 89 importers, 300 lines, mixing timezone config, ChangeSpec branch naming, shell
   execution, directory management, and hook parsing. It's the single most imported module in the codebase.

2. **`sase_utils` vs `shared_utils` naming is confusing.** Both names say "utilities" but they serve different layers.
   `sase_utils` is lower-level infrastructure; `shared_utils` is higher-level workflow/artifacts management.

3. **Agent lifecycle code is scattered.** Four related files sit loose at the package root with no grouping, while the
   existing `axe/` subpackage handles adjacent agent execution concerns.

4. **`sdd.py` is a domain module masquerading as a utility.** It imports from `bead`, `config`, `gemini_wrapper`,
   `llm_provider`, and `workspace_provider` — it's a cross-cutting coordinator for the SDD feature, not a utility.

## Best practices research

### Python package organization principles

**The Python Packaging Guide** and widely-adopted conventions (e.g., from _Architecture Patterns with Python_ by
Percival & Gregory, and the Django/FastAPI ecosystems) recommend:

1. **Group by domain, not by layer.** Files should be grouped by what feature they serve, not by what kind of code they
   contain. A `utils.py` file is a smell when it grows past ~200 lines or ~10 importers — it means the functions have
   natural homes elsewhere.

2. **Keep the package root thin.** The top-level `__init__.py` and `__main__.py` should be the only files at the root.
   Everything else should live in a subpackage. This makes the package scannable: `ls src/sase/` should show feature
   areas, not a flat list of 8+ modules.

3. **Utility modules should be small and focused.** When a utility module grows beyond ~150 lines, it usually means it's
   accruing responsibilities that belong in domain-specific modules. Preferred pattern: one utility module per concern
   (e.g., `time.py`, `paths.py`, `shell.py`).

4. **Avoid "utils" in the name when possible.** Names like `sase_utils` and `shared_utils` don't communicate what's
   inside. Better names describe the domain (`timestamps.py`, `artifacts.py`, `changespec_naming.py`).

5. **Subpackage threshold: 3+ related files.** When you have 3 or more files that share a domain, they warrant a
   subpackage with an `__init__.py` that re-exports the public API.

### Anti-patterns observed

- **Two "utils" files** at the same level (`sase_utils.py` and `shared_utils.py`) is a classic sign of ad-hoc growth
  where the second file was created because the first was already too large.
- **God module** (`sase_utils.py` at 89 importers) creates hidden coupling: changes to timezone logic could
  theoretically affect ChangeSpec naming code since they share a module.
- **Flat structure with implicit grouping** — the four `agent_*`/`multi_prompt_*` files are related by convention
  (similar prefixes) but not by structure.

## Recommended grouping

### Option A: Subpackages (recommended)

```
src/sase/
├── __init__.py
├── __main__.py
├── agent/                          # NEW subpackage
│   ├── __init__.py                 # Re-exports public API
│   ├── launcher.py                 # ← agent_launcher.py
│   ├── names.py                    # ← agent_names.py
│   ├── multi_prompt.py             # ← multi_prompt.py
│   └── multi_prompt_launcher.py    # ← multi_prompt_launcher.py
├── sdd/                            # NEW subpackage (or fold into bead/)
│   ├── __init__.py
│   ├── files.py                    # ← sdd.py (write_sdd_files, commit_sdd_files, etc.)
│   └── beads.py                    # ← sdd.py (ensure_beads_initialized, _init_beads)
├── output.py                       # ← rich_utils.py (rename for clarity)
├── core/                           # NEW subpackage — split sase_utils.py
│   ├── __init__.py                 # Re-exports everything for backward compat
│   ├── time.py                     # get_timezone, generate_timestamp
│   ├── paths.py                    # get_sase_directory, ensure_sase_directory,
│   │                               #   get_sase_tmpdir, shorten_path, make_safe_filename
│   ├── shell.py                    # run_shell_command, run_workspace_command,
│   │                               #   get_vendored_tool
│   └── changespec.py               # strip_reverted_suffix, changespec_name_to_branch,
│                                   #   has_suffix, get_next_suffix_number, etc.
├── artifacts.py                    # ← shared_utils.py (create_artifacts_directory,
│                                   #   initialize_workflow, workflow log functions,
│                                   #   convert_timestamp_to_artifacts_format)
├── content.py                      # ← shared_utils.py (apply_section_marker_handling,
│                                   #   content_ends_with_markdown_heading,
│                                   #   ensure_str_content, dump_yaml)
└── ... (existing subpackages)
```

**Pros:** Clean separation of concerns. Each module is small and descriptively named. The `agent/` subpackage makes the
domain boundary explicit.

**Cons:** Many import paths change (89 importers of `sase_utils` alone). Needs a careful migration with re-exports for
backward compatibility.

### Option B: Minimal restructure (lower risk)

Keep files at the package root but rename and split the two problematic modules:

```
src/sase/
├── __init__.py
├── __main__.py
├── agent_launcher.py               # Keep as-is
├── agent_names.py                  # Keep as-is
├── multi_prompt.py                 # Keep as-is
├── multi_prompt_launcher.py        # Keep as-is
├── rich_utils.py                   # Keep as-is
├── sdd.py                          # Keep as-is
├── time_utils.py                   # ← from sase_utils.py (timezone, timestamps)
├── path_utils.py                   # ← from sase_utils.py (dirs, tmpdir, filenames)
├── shell_utils.py                  # ← from sase_utils.py (run_shell_command, etc.)
├── changespec_utils.py             # ← from sase_utils.py (naming, branching)
├── artifacts.py                    # ← from shared_utils.py (artifacts, workflow init)
├── content_utils.py                # ← from shared_utils.py (section markers, yaml, etc.)
└── sase_utils.py                   # Kept as re-export shim for backward compat
```

**Pros:** Lower migration risk. `sase_utils.py` can be kept as a thin re-export shim (`from sase.time_utils import *`,
etc.) so existing imports don't break.

**Cons:** Doesn't address the agent lifecycle grouping. Still a flat structure with many files.

### Option C: Hybrid (recommended for incremental adoption)

Do Option A for the agent files (clear domain boundary, only 5-6 importers each) and Option B for the utils files (lower
risk for the 89-importer `sase_utils`):

1. Create `agent/` subpackage immediately (low risk, clear win).
2. Split `sase_utils.py` into focused modules with a re-export shim (medium risk, high value).
3. Rename `shared_utils.py` → `artifacts.py` + `content_utils.py` (medium risk).
4. Evaluate moving `sdd.py` into `bead/` or a new `sdd/` subpackage later.

## Migration strategy for any option

1. Create new modules/subpackages with the actual code.
2. Replace original files with re-export shims:
   ```python
   # sase_utils.py (backward-compat shim)
   from sase.core.time import get_timezone, generate_timestamp  # noqa: F401
   from sase.core.paths import get_sase_directory, ...          # noqa: F401
   # etc.
   ```
3. Run `just check` to verify nothing breaks.
4. Over subsequent PRs, update importers to use new paths and remove shims.

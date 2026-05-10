---
create_time: 2026-03-22 15:27:52
status: done
prompt: sdd/prompts/202603/config_debuggability.md
---

# Plan: Config & Mentor Profile Debuggability

## Problem

The bug fixed in `725a4aa` was hard to diagnose because:

1. No way to see what each config layer contributes to the merged result
2. No way to see when lists are replaced vs concatenated during merge
3. No way to trace mentor profile matching decisions for a given ChangeSpec
4. No CLI command to inspect the final merged config or test profile matching

An agent debugging this had to: read `config/core.py`, find all config files on disk, manually trace merge logic, then
read `mentor_profile_matching.py` and mentally simulate matching — all without any tooling support.

## Solution: `sase config` CLI Subcommand

Add a new `sase config` top-level command with diagnostic subcommands. This follows the existing pattern of
`sase xprompt {expand,list,graph,explain}`.

### Phase 1: `sase config show` — Merged Config Dump

**What it does**: Prints the final merged config as YAML to stdout.

**Why it helps**: An agent can run `sase config show | grep mentor_profiles` to immediately see what profiles are
loaded, without reading code.

**Implementation**:

- Add `config` parser + `show` subparser in `src/sase/main/parser.py`
- Add handler in `src/sase/main/entry.py` that calls `load_merged_config()` and prints YAML
- Optional `--key` flag to extract a specific key (e.g., `sase config show --key mentor_profiles`)

**Files to modify**:

- `src/sase/main/parser.py` — add `config` subcommand with `show` subparser
- `src/sase/main/entry.py` — add handler block

### Phase 2: `sase config layers` — Per-Layer Breakdown

**What it does**: Shows each config layer (default → plugins → user → overlays → local) with:

- Source file path
- Whether the file exists/was loaded
- List merge strategy used ("concatenate" or "replace")
- Keys contributed by that layer (top-level keys only, to keep output concise)

**Why it helps**: Would have immediately shown "local `./sase.yml` contributes `mentor_profiles` with concatenate
strategy" — making it obvious that the local file affects mentor profiles. Before the fix, it would have shown "replace"
and immediately flagged the root cause.

**Implementation**:

- Add a new function `load_config_layers()` in `src/sase/config/core.py` that returns a list of layer descriptors
  (source path, loaded data, merge strategy) instead of a single merged dict
- Add `layers` subparser in parser.py
- Handler prints each layer as a Rich table or structured YAML

**New types** (in `src/sase/config/core.py`):

```python
@dataclass
class ConfigLayer:
    name: str              # e.g., "default", "plugin:retired_mercurial_plugin", "user", "overlay:sase_hg.yml", "local"
    path: str | None       # File path, or None for built-in defaults
    exists: bool           # Whether the file was found
    list_strategy: str     # "concatenate" or "replace"
    keys: list[str]        # Top-level keys contributed
    data: dict[str, Any]   # The raw data from this layer
```

**Files to modify**:

- `src/sase/config/core.py` — add `ConfigLayer` dataclass and `load_config_layers()` function
- `src/sase/main/parser.py` — add `layers` subparser
- `src/sase/main/entry.py` — add handler

### Phase 3: `sase config mentor-match` — Profile Matching Trace

**What it does**: Given a ChangeSpec name, shows which mentor profiles matched and why, or why they didn't match. Output
per profile:

- Profile name + source (which config layer defined it)
- Match criteria (file_globs, diff_regexes, amend_note_regexes, first_commit)
- Match result per criterion (MATCH / NO MATCH / SKIPPED)
- For file_globs: which files were checked and whether any matched
- For diff_regexes: whether any regex matched the diff content

**Why it helps**: Would have shown "Profile 'aaa': NOT LOADED (not in merged config)" — immediately revealing that
plugin profiles were missing from the merged config.

**Implementation**:

- Add a `trace_profile_matching()` function in `src/sase/ace/scheduler/mentor_profile_matching.py` that returns
  structured match results instead of just a bool
- Add `mentor-match` subparser that takes a ChangeSpec name
- Handler loads the ChangeSpec, runs trace matching, prints results

**New types** (in `src/sase/ace/scheduler/mentor_profile_matching.py`):

```python
@dataclass
class ProfileMatchTrace:
    profile_name: str
    criteria_results: list[CriterionResult]
    overall_match: bool

@dataclass
class CriterionResult:
    criterion: str         # "file_globs", "diff_regexes", etc.
    configured: bool       # Whether this criterion exists on the profile
    matched: bool
    details: str           # e.g., "*.py matched src/sase/foo.py"
```

**Files to modify**:

- `src/sase/ace/scheduler/mentor_profile_matching.py` — add trace function
- `src/sase/main/parser.py` — add `mentor-match` subparser
- `src/sase/main/entry.py` — add handler

### Phase 4: Debug Logging in Config Merge

**What it does**: Add `log.debug()` calls to `_deep_merge()` that trace list merge decisions.

**Why it helps**: When running with `SASE_LOG_LEVEL=DEBUG` or similar, the merge trace appears in logs automatically —
useful for post-mortem debugging without needing to reproduce.

**Implementation**:

- In `_deep_merge()`, log when a list key is being merged and which strategy is used:
  ```
  DEBUG config.core: Merging key 'mentor_profiles': list concatenate (base=5 items, override=2 items → 7 items)
  ```
  or:
  ```
  DEBUG config.core: Merging key 'mentor_profiles': list replace (base=5 items → override=2 items)
  ```
- In `load_merged_config()`, log each layer as it's loaded:
  ```
  DEBUG config.core: Loading layer 'plugin:retired_mercurial_plugin' from /path/to/default_config.yml (keys: mentor_profiles, xprompts)
  DEBUG config.core: Loading layer 'local' from ./sase.yml (keys: mentor_profiles) [list_strategy=concatenate]
  ```

**Files to modify**:

- `src/sase/config/core.py` — add debug log calls

## Phase Order and Dependencies

1. **Phase 4** (logging) — smallest change, immediate value, no new CLI surface
2. **Phase 1** (`config show`) — simple, high value, foundation for other phases
3. **Phase 2** (`config layers`) — moderate complexity, the most diagnostic value for config bugs
4. **Phase 3** (`config mentor-match`) — most complex, but essential for mentor-specific debugging

## Testing Strategy

- Phase 1-2: Unit tests for `load_config_layers()` with mock config files
- Phase 3: Unit tests for `trace_profile_matching()` with synthetic ChangeSpecs
- Phase 4: No tests needed (debug logging)
- All phases: Manual verification with `just check`

---
bead_id: sase-efk
---

# Plan: TUI Cache Chops for Agents Tab Optimization

## Context

Navigating the Agents tab in `sase ace` with j/k keys is slow because each agent selection triggers expensive on-the-fly
computation:

1. **File panel**: Spawns `git diff HEAD` + `git ls-files --others` subprocesses (10s timeout) per workspace
2. **Thinking panel**: Resolves Claude Code JSONL session files and parses thinking blocks from large files

Both panels have in-memory caches (10s staleness), but caches are per-agent so switching agents always misses for a new
agent.

**Solution**: Create 2 new chops in a new `tui_cache` lumberjack (5s interval) that pre-generate and cache this data
while `sase axe` runs. The TUI reads cached files instead of computing on-the-fly, falling back to live computation on
cache miss.

## Phase 1: Diff Cache Chop + Infrastructure

**Goal**: Create cache utilities, the `agent_diff_cache` chop, the new `tui_cache` lumberjack, and wire the TUI file
panel to read from cache.

### New files

1. **`src/sase/axe/tui_cache.py`** - Cache path utilities
   - `DIFF_CACHE_DIR = ~/.sase/axe/cache/diffs/`
   - `THINKING_CACHE_DIR = ~/.sase/axe/cache/thinking/`
   - `diff_cache_path(project_basename, workspace_num) -> Path` - returns `{DIFF_CACHE_DIR}/{project}_{workspace}.diff`
   - `thinking_cache_path(project_basename, workspace_num) -> Path` - returns
     `{THINKING_CACHE_DIR}/{project}_{workspace}.json`
   - `is_cache_fresh(path, max_age_seconds) -> bool` - checks file exists and mtime is fresh
   - `ensure_cache_dirs()` - creates directory tree

2. **`src/sase/scripts/sase_chop_agent_diff_cache.py`** - Diff cache chop
   - Pattern: same as `sase_chop_hook_checks.py` (argparse, `read_chop_context`, `load_changespecs_from_file`)
   - Iterate unique project files from changespecs
   - For each, call `get_claimed_workspaces(project_file)` to find running agents
   - For each claim, compute diff using `git_diff_with_untracked()` / `git_committed_diff()` / `hg diff`
   - Write to `diff_cache_path(project_basename, claim.workspace_num)` atomically (`.tmp` + rename)
   - Clean up stale cache files for workspaces no longer running
   - **Reuse**: `sase.running_field.get_claimed_workspaces`, `sase.running_field.get_workspace_directory`,
     `sase.gh_workspace.detect_vcs_type_for_project`, `sase.git_utils.git_diff_with_untracked`,
     `sase.git_utils.git_committed_diff`

### Modified files

3. **`src/sase/default_config.yml`** - Add `tui_cache` lumberjack:

   ```yaml
   tui_cache:
     interval: 5
     chops:
       - name: agent_diff_cache
         description: "Pre-warm diff cache for running agent workspaces"
   ```

4. **`pyproject.toml`** - Add entry point: `sase_chop_agent_diff_cache = "sase.scripts:sase_chop_agent_diff_cache"`

5. **`src/sase/scripts/__init__.py`** - Add wrapper function (same pattern as existing chops)

6. **`src/sase/ace/tui/widgets/file_panel/_diff.py`** - Modify `get_agent_diff()`:
   - At the top, check `diff_cache_path()` with `is_cache_fresh(max_age_seconds=15.0)`
   - Only for agents with `workspace_num` and NOT in DONE/FAILED status
   - On cache hit: return cached content (or None if empty)
   - On miss: fall through to existing subprocess logic (graceful degradation)

### Verification

- `just check` (fmt + lint + test)
- Run `sase axe chop run agent_diff_cache` manually, verify `.diff` files appear at `~/.sase/axe/cache/diffs/`
- `sase ace --agent` to verify TUI still renders correctly

---

## Phase 2: Thinking Cache Chop + TUI Integration

**Goal**: Create the `agent_thinking_cache` chop and wire the TUI thinking panel to read from cache.

### New files

1. **`src/sase/scripts/sase_chop_agent_thinking_cache.py`** - Thinking cache chop
   - Same pattern: iterate project files, get claimed workspaces
   - For each workspace, resolve Claude project dir: workspace CWD -> hash -> `~/.claude/projects/{hash}/`
   - Find JSONL files, call `parse_thinking_blocks_multi()`
   - Serialize `ThinkingBlock` list to JSON with `source` field (for Gemini vs Claude)
   - Write to `thinking_cache_path()` atomically
   - Clean up stale cache files
   - Handle Gemini fallback: when no JSONL files exist and default provider is Gemini, use `read_gemini_log()`
   - **Reuse**: `sase.ace.tui.thinking.parser.parse_thinking_blocks_multi`, `sase.ace.tui.thinking.read_gemini_log`,
     `sase.ace.tui.thinking.session_resolver._cwd_to_claude_project_dir` (or reimplement the hash logic inline),
     `sase.llm_provider.registry.get_default_provider_name`

### Modified files

2. **`src/sase/default_config.yml`** - Add `agent_thinking_cache` to `tui_cache` lumberjack

3. **`pyproject.toml`** - Add entry point

4. **`src/sase/scripts/__init__.py`** - Add wrapper function

5. **`src/sase/ace/tui/widgets/thinking_panel.py`** - Modify `_fetch_thinking_in_background()`:
   - At the top, check `thinking_cache_path()` with `is_cache_fresh(max_age_seconds=15.0)`
   - Only for agents with `workspace_num`
   - On cache hit: deserialize ThinkingBlock list from JSON, populate in-memory cache, return
   - On miss: fall through to existing session resolution logic
   - Handle `source` field from JSON for Gemini styling

### Verification

- `just check`
- Run `sase axe chop run agent_thinking_cache`, verify `.json` files at `~/.sase/axe/cache/thinking/`
- Navigate Agents tab with j/k, observe faster loading (no "Loading..." flash on agent switch)

---

## Phase 3: Edge Cases, Cleanup, and Polish

**Goal**: Robust cache cleanup, edge case handling, and end-to-end polish.

### Modified files

1. **Both chop scripts** - Enhance cache cleanup:
   - After caching active workspaces, scan cache dirs and remove files for workspaces no longer claimed
   - Parse filename `{project}_{workspace_num}.{ext}` to identify stale entries

2. **`src/sase/axe/tui_cache.py`** - Add `cleanup_all_caches()` for when axe stops

3. **`src/sase/ace/tui/widgets/file_panel/_diff.py`** - Safety: explicitly skip cache for DONE/FAILED agents

4. **`src/sase/ace/tui/widgets/thinking_panel.py`** - Handle extended JSON format with `source` field for Gemini styling

5. **Tests** - Add/update tests:
   - `tests/test_tui_cache.py` - cache path utilities, staleness checks, cleanup
   - `tests/test_chop_agent_diff_cache.py` - mocked workspace/VCS, atomic writes, cleanup
   - `tests/test_chop_agent_thinking_cache.py` - JSON serialization, Gemini fallback, cleanup

### Verification

- `just check` (full suite)
- Start agents, stop them, verify stale cache files cleaned up within ~5s
- Full flow: `sase axe` running, navigate Agents tab rapidly with j/k, confirm no "Loading..." flash
- Verify graceful degradation when axe is NOT running (TUI falls back to live fetch)

---

## Key Design Decisions

- **Cache location**: `~/.sase/axe/cache/{diffs,thinking}/` under the existing axe state dir
- **Staleness**: Use file mtime, TUI accepts cache up to 15s old (lumberjack runs every 5s)
- **Atomic writes**: `.tmp` + rename prevents partial reads
- **Graceful degradation**: Cache miss = existing behavior; TUI works identically without axe running
- **Scope**: Only cache running agents (DONE/FAILED use pre-saved `agent.all_files`)

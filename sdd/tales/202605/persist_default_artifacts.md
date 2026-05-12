---
create_time: 2026-05-11 20:28:23
status: completed
prompt: sdd/prompts/202605/persist_default_artifacts.md
---
# Plan: Persist auto-discovered agent artifacts to `~/.sase/artifacts/`

## Problem

The "ARTIFACTS:" entries in the `sase ace` Agent Details panel break as soon as the agent's `sase_<N>` workspace is
reused by the next agent. The artifact still appears in the panel, but clicking it opens a dead path.

Concrete reproduction (from today): agent `@l4.r1.r1` lists
`sdd/research/202605/last_workflow_set_status_script_infographic.png` under ARTIFACTS, but the file is gone because
workspace #100 was cleared.

## Root cause

There are two "kinds" of agent artifacts today, and only one is persistent:

| Kind               | Discovered via                                                                   | Stored where                                                                                  | Survives workspace cleanup? |
| ------------------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | --------------------------- |
| **Explicit**       | `sase artifact create` skill call                                                | Copied/moved to `~/.sase/artifacts/agents/...` and indexed in `~/.sase/artifacts/index.jsonl` | ✅ Yes                      |
| **Default (auto)** | `done.json:image_paths` + xprompt regex scan in `_discover_prompt_image_paths()` | Left where the agent wrote them — inside `sase_<N>/...`                                       | ❌ No                       |

The artifacts panel resolver (`_resolve_actual_path` in
`src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py:134-140`) joins `workspace_dir + relative_path`. Workspace
gone → path dead.

The infrastructure for global storage already exists (`store_explicit_agent_artifact()`,
`~/.sase/artifacts/index.jsonl`). It is simply not wired into the default-discovery path.

## Goal

Auto-discovered artifacts must survive workspace reuse. The Agent Details panel must display a stable, human-readable
label and open a file that still exists.

Out of scope: recovering artifacts from already-broken historical agents; garbage-collecting the global store; changing
the explicit `sase artifact create` flow.

## Approach: persist at agent-done time, single source of truth in the JSONL index

### Hook point

The only reliable moment to copy artifact files is when the agent has finished but its workspace is still on disk. That
moment is `run_execution_loop()` in `src/sase/axe/run_agent_exec.py`, specifically the success branch around lines
429-467, right after `collect_agent_image_paths()` and right before `build_done_marker()` / `done.json` write.

A single new call inserted there — call it `persist_default_agent_artifacts()` — will:

1. Take the existing `image_paths` list (already collected from the workspace diff).
2. Re-run the same xprompt-image discovery that the panel currently does lazily (`_discover_prompt_image_paths()` in
   `agent_artifact_defaults.py:149`). Doing it here, once, while files exist, removes the need to do it again on every
   panel render.
3. For each existing source file, copy it into the global store using the existing layout
   (`~/.sase/artifacts/agents/<project>/<timestamp>/<stem>-<digest><suffix>`), and append a row to `index.jsonl`.

The failure / `plan_rejected` / `killed` branch (lines 491–512) skips this step — those agents typically have nothing to
persist, and we don't want a side effect on the unhappy path.

### Storage API changes

`src/sase/core/agent_artifact_explicit.py` already contains `_store_file()` and `_upsert_index_row()` — the two
primitives we need. Two refactor options:

- **(Recommended)** Extract a shared `store_agent_artifact_file()` helper that takes a new `explicit: bool` parameter,
  and have both `store_explicit_agent_artifact()` and a new `store_default_agent_artifact()` delegate to it. Keep the
  `explicit` flag in the index row so we can tell them apart later (e.g. for filtering, GC, or different UI styling).
- Alternative: pass `explicit=False` directly to `store_explicit_agent_artifact()`. Smaller diff, but the function name
  becomes misleading.

The index row for a default artifact should record **both** the persisted absolute path (`AgentArtifact.path`) **and**
the original workspace path (`AgentArtifact.source_path`). The latter is what the panel will display to the user.

### Discovery / synthesis changes

`synthesize_default_agent_artifacts()` in `agent_artifact_defaults.py` currently invents artifact rows from
`done.json:image_paths` and from xprompt scanning, with `workspace_dir`-relative paths. After this change, those rows
are redundant — the index JSONL is now the source of truth for the same set.

The new behaviour:

- `list_agent_artifacts()` reads explicit + default rows from the index for this agent
  (`list_explicit_agent_artifacts()` widened to "all index rows for this agent association", since `explicit=False` rows
  now also live there).
- The image-discovery branch of `synthesize_default_agent_artifacts()` (lines 83-107) becomes a **fallback only for
  agents whose `done.json` predates this feature** — i.e., when the index has no rows for this agent and
  `done.json:image_paths` is present. We can keep the old code path behind a "no index rows found" check so we don't
  break display of older agents whose artifacts may still happen to exist on disk.
- `chat` and `plan` artifacts continue to be synthesized as before — those live inside the agent's persistent artifacts
  directory (`~/.sase/projects/.../artifacts/...`), not in the ephemeral workspace, so they don't have the same problem.

### Panel resolver changes

`_resolve_actual_path()` in `_agent_artifacts.py` and `_display_path()` need light edits:

- When `artifact.path` is already absolute (the new persisted case), use it directly and ignore `workspace_dir`.
- Use `artifact.source_path` (when present) to derive the display label — render it workspace-relative if possible so
  the user sees `sdd/research/202605/foo.png` rather than `~/.sase/artifacts/agents/sase/.../foo-abc123def012.png`.

### Missing-file UX

Existing agents whose workspace is already gone cannot be repaired. For those:

- The panel should detect a missing resolved path and dim the entry plus append ` (missing)`. Keep it visible rather
  than hiding it, so users still understand what the agent _produced_.
- Implemented in `_dedupe_paths()` / `_append_path()` with an `os.path.exists()` check.

This is a small change but worth bundling — it converts the current silent failure into a legible one for the historical
agents.

## Tests

Existing tests in `tests/test_agent_artifact_facade.py`, `tests/test_artifacts.py`, and
`tests/test_agent_artifact_e2e.py` give us a foundation. New / extended tests:

1. **Unit — `store_default_agent_artifact()`**: given a workspace file, copies it to the global store under the expected
   layout, writes a row to `index.jsonl` with `explicit=False` and `source_path` set to the original location.
2. **Unit — `persist_default_agent_artifacts()`**: integrates `image_paths` + xprompt discovery; idempotent (running
   twice yields the same paths, no duplicate index rows); silently skips paths that don't exist on disk.
3. **Integration — agent-done write path**: end-to-end fixture in `run_agent_exec` that creates a fake workspace with a
   PNG, runs the finalization, then deletes the workspace, then asserts `list_agent_artifacts()` still returns the
   artifact and its resolved path exists.
4. **Panel — missing file rendering**: an artifact whose `path` no longer exists is rendered dimmed with a `(missing)`
   suffix.
5. **Backward compat**: an older agent dir with `done.json:image_paths` but no index rows still surfaces artifacts via
   the legacy synthesis fallback.

## Risks and decisions for the user

- **Schema compatibility**: writing `explicit=False` rows to `index.jsonl` is a semantic widening, not a schema break —
  the existing `explicit: bool` field already exists in the dataclass and on-disk format. No version bump needed.
- **Disk usage**: every agent will now copy its discovered PNGs into `~/.sase/`. For research/image-heavy agents this is
  real bytes. Acceptable for now; a separate GC/retention task is the right follow-up.
- **xprompt regex false positives**: `_IMAGE_PATH_RE` is currently used at display time, where false positives are
  filtered by `is_file()`. We must preserve that `is_file()`-gate at persistence time so we don't try to copy
  nonexistent matches.
- **Open question**: should we also persist `markdown_pdf_paths`? They already live in the agent's persistent artifacts
  directory (not in the workspace), so they shouldn't have this bug — leave them alone for this change.

## Deliverables

1. New module `src/sase/core/agent_artifact_persistence.py` (or top-level function in `agent_artifact_explicit.py`) with
   `persist_default_agent_artifacts()` and supporting helpers.
2. Edits to `src/sase/axe/run_agent_exec.py` to invoke persistence in the success branch.
3. Edits to `src/sase/core/agent_artifact_defaults.py` to fall back to legacy synthesis only when no index rows exist.
4. Edits to `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py` for absolute-path resolution, source-path-based
   display, and missing-file marking.
5. Tests as listed above.

No CLI changes, no migration script. New agents persist their artifacts immediately; old agents render legibly even when
their workspace is gone.

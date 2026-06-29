---
create_time: 2026-06-29 10:13:03
status: done
prompt: sdd/prompts/202606/project_display_name_everywhere.md
---
# Show `PROJECT_NAME` (not the directory key) in **all** remaining user-facing surfaces

## Problem

A project can define a logical `PROJECT_NAME` in its `.sase` spec (e.g. the project whose canonical directory key is
`gh_bbugyi200__actstat` has `PROJECT_NAME: actstat`). The principle is: **whenever we show a project to a human, we show
its logical name, never the verbose canonical directory key.**

Recent work wired the logical name into several surfaces (agent-row label, agent/workflow detail "Project:" field, the
"by project" grouping banner, tmux window names, saved-group project records). But a screenshot of the Agents tab shows
the directory key still leaking in the right-hand agent detail panel:

```
Xprompts: 1 workflow · 2 parts
  ⌘ #gh   gh_bbugyi200__actstat      <-- should read: actstat
     #plan
     #m_opus
...
AGENT XPROMPT

#gh:gh_bbugyi200__actstat GitHub Actions for this repo seem to be failing...   <-- should read: #gh:actstat
```

A broader sweep found the same leak in additional surfaces outside the Agents-tab panel (AXE background-command panels
and dialogs, command history, and prompt-input completion). This plan fixes the screenshot violation and every other
violation found, while leaving storage/identity/dedup/path logic (which must keep the canonical key) untouched.

## Root Cause

There are two distinct mechanisms producing the leak, and the remaining surfaces fall into two groups accordingly.

### Mechanism A — Agents-tab detail panel reads canonicalized launch text

At launch, `canonicalize_project_aliases_in_prompt()` rewrites the user-typed `#gh:actstat` into the canonical
`#gh:gh_bbugyi200__actstat` (so launch/identity is deterministic). That canonicalized text is what gets persisted and
later parsed for display:

- `raw_xprompt.md` is written from the canonicalized prompt
  (`src/sase/axe/run_agent_runner_setup.py:preprocess_prompt_xprompts`), and the panel's **AGENT XPROMPT** section
  renders it verbatim (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_render.py`, via `get_raw_xprompt_content`).
- `xprompts.json` is collected from that **same canonicalized** text (`write_used_xprompts(... prompt)` in the same
  function → `collect_used_xprompts` in `src/sase/xprompt/used_xprompts.py`). For a `#gh:actstat` launch the recorded
  `#gh` workflow entry therefore has `positional == ["gh_bbugyi200__actstat"]`. The **Xprompts** panel section
  (`src/sase/ace/tui/widgets/prompt_panel/_agent_xprompts.py::_format_args`) prints that positional value verbatim.

The original `#gh:actstat` text is _not_ preserved anywhere readable (the `submitted_xprompt.md` artifact is also
written post-canonicalization). So these two surfaces must substitute the logical name **at render time**.

Crucially, the data needed is already cached with zero extra work: `Agent.project_display_name` (populated once per
refresh by `_attach_project_display_names` in `src/sase/ace/tui/actions/agents/_loading_compute.py`) holds the logical
name for the agent's own project, and that project's directory key is exactly the value leaking in both surfaces.

### Mechanism B — Non-agent surfaces print a raw project directory key

These surfaces render a project directory key held on a non-`Agent` model that has no cached display name:

- **AXE background commands** carry `BackgroundCommandInfo.project` (a directory key; `src/sase/ace/tui/bgcmd.py`).
  Every AXE surface reads it through the single `get_slot_info()` accessor:
  - AXE info panel top bar — `src/sase/ace/tui/widgets/axe_info_panel.py` (`self._bgcmd_info.project`).
  - AXE dashboard status header — `src/sase/ace/tui/widgets/_axe_dashboard_status.py` (`info.project`).
  - Process-select modal description — `src/sase/ace/tui/modals/process_select_modal.py` (`f"{info.project} ..."`).
  - Confirm-kill / confirm-rerun dialog descriptions — `src/sase/ace/tui/actions/axe_bgcmd.py`
    (`f"... ({info.project}, workspace ...)"`).
- **Command history modal** renders `entry.project` (directory key) as dimmed context —
  `src/sase/ace/tui/modals/command_history_modal.py`.
- **Prompt-input completion** renders `entry.project` (directory key) for changespec-history suggestions —
  `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py`.

The reverse mapping directory-key → logical name already exists and is used widely in modals:
`project_display_name_map(list_project_records(...))` / `effective_project_name(record)`
(`src/sase/core/project_lifecycle_wire.py`). `effective_project_name` returns the `PROJECT_NAME` if set, else the
directory key — a safe fallback.

## Goal / Target Behavior

For any project whose spec defines a `PROJECT_NAME`, the logical name (e.g. `actstat`) is shown — never the directory
key (`gh_bbugyi200__actstat`) — in:

1. the agent detail panel's **Xprompts** argument list,
2. the agent detail panel's **AGENT XPROMPT** body,
3. the AXE info panel, AXE dashboard status, process-select modal, and confirm-kill/rerun dialogs,
4. the command-history modal context, and
5. prompt-input changespec-history completion.

Projects without a `PROJECT_NAME` are unchanged (they keep displaying by directory key, via the existing fallback).
Nothing about identity, dedup, storage paths, launch/canonicalization, grouping keys, or the `project:` query filter
changes — only what is _shown_.

This is a `sase`-repo-only, display-layer change. No `sase-core` (Rust) or `sase-github` changes are required: the
`PROJECT_NAME` is already parsed, stored, resolved, and exposed via the existing wire layer.

## Design

Two independent parts. Part A (the screenshot) is the primary, lowest-risk fix and stands on its own; Part B extends the
principle to the remaining surfaces via one shared, cache-backed resolver.

### Part A — Agents-tab detail panel (fixes the screenshot)

Reuse the already-populated, already-cached `Agent.project_display_name`. No new disk reads — both fixes are pure
in-memory reads of a field filled once per refresh.

- **A1. Xprompts argument list.** In `_agent_xprompts.py`, when formatting a recorded xprompt's positional/named args,
  substitute the agent's logical name for any argument value that equals the agent's own project directory key. Thread
  the selected `agent` (or just its `(directory_key, project_display_name)` pair) from `build_header_text`
  (`_agent_display_header.py`, which already holds `agent`) into `append_agent_xprompts_section`. When
  `project_display_name` is unset or no arg matches, behavior is identical to today.

- **A2. AGENT XPROMPT body.** In `_agent_display_render.py`, before appending `get_raw_xprompt_content()`, run a small,
  targeted reverse substitution that rewrites the agent's own project's VCS launch refs `#<prefix>:<dir_key>` and
  `#<prefix>(<dir_key>)` → `#<prefix>:<project_display_name>`. Scope the rewrite to the VCS-ref pattern (mirroring the
  canonicalizer) and to the agent's own directory key only — never a blind whole-text find/replace — so paths or
  unrelated text that happen to contain the key are not disturbed. Implement this as a reverse companion to
  `canonicalize_project_aliases_in_prompt` (a "humanize project refs in text" helper that takes text + a
  `{dir_key: display_name}` map), placed beside it in `src/sase/project_aliases.py` for symmetry and reuse by Part B.

Why Part A is safe (display-only):

- Identity/dedup/option IDs use `cl_name`/`identity`, not these rendered strings.
- The Xprompts panel and AGENT XPROMPT sections render only for the single selected agent (not per row), so there is no
  per-row cost, and Part A adds no disk reads at all (it reads the cached `project_display_name`).
- Worst case is cosmetic: an agent without a populated `project_display_name` (e.g. a revived agent, which intentionally
  does not persist the field) simply falls back to today's directory-key display.

### Part B — Remaining surfaces via one shared, cached resolver

Add a single display-only resolver `project_display_name_for(key) -> str` (logical name if the project defines
`PROJECT_NAME`, else the key unchanged). Back it by `project_display_name_map(list_project_records(...))`, **cached and
keyed by the projects-directory mtime** so it never re-reads project records on a hot path (TUI perf rule: cache disk
reads keyed by mtime; invalidate only on structure-changing events). This mirrors the resolver
`_attach_project_display_names` already uses, but as a reusable, on-demand accessor for non-`Agent` call sites. Per the
Rust-core boundary, this is a thin presentation-layer adapter over the existing wire API (`list_project_records` already
sources from the Rust core) — no core change.

Apply it at the leak sites:

- **B1. AXE background-command surfaces.** Resolve the display name from `BackgroundCommandInfo.project` at the four
  render/description sites (info panel, dashboard status, process-select modal, confirm-kill/rerun dialogs). Because all
  four read through `get_slot_info()`, prefer a single chokepoint: expose the resolved logical name once (e.g. a
  display-only helper/property derived from `info.project` via the cached resolver) and have all four sites use it, so
  the rule is enforced in one place rather than four. The cached resolver keeps the per-frame info-panel/dashboard paths
  free of new disk reads.
- **B2. Command-history modal.** Replace the raw `entry.project` in the modal's context column and details preview with
  the resolved logical name.
- **B3. Prompt-input completion.** Replace the raw `entry.project` in changespec-history completion rows with the
  resolved logical name.

Modal/completion paths are on-demand (not per-frame); the cached resolver makes even the persistent AXE panels safe.

### Out of scope

- No changes to `sase-core` (Rust) or `sase-github`.
- No change to storage identity, path computation, alias/`#gh:` canonicalization, grouping keys, tmux/saved-group code
  (already handled), or the `project:` query filter.
- No migration of existing agents/projects; projects without `PROJECT_NAME` are unchanged.
- The **AGENT PROMPT** (fully expanded, LLM-bound) body is left as-is unless it is found to surface a project directory
  key in practice; it is the post-expansion artifact and is treated as the faithful record of what ran. (The AGENT
  XPROMPT body in A2 is the user-facing pre-expansion echo and is the one the screenshot flags.)

## Tests

Add focused, display-layer tests next to existing suites; construct project agents/records so a directory key maps to a
distinct `PROJECT_NAME`.

Part A (extend `tests/ace/tui/widgets/test_agent_display_list_rendering.py` /
`tests/ace/tui/widgets/test_agent_display_project_names.py` style harness):

1. **Xprompts arg uses logical name.** A project agent with directory key `gh_acme__widgets`,
   `project_display_name="widgets"`, and a recorded `#gh` workflow entry with `positional=["gh_acme__widgets"]` →
   rendered Xprompts line contains `widgets` and not `gh_acme__widgets`.
2. **Xprompts arg fallback unchanged.** Same entry with `project_display_name=None` → still shows `gh_acme__widgets`.
   Non-project-key positional args (e.g. a literal flag) are never rewritten.
3. **AGENT XPROMPT body uses logical name.** Body `#gh:gh_acme__widgets do X` with `project_display_name="widgets"` →
   rendered body contains `#gh:widgets`; a directory key appearing in a non-ref context (e.g. inside a path) is left
   intact.

Part B:

4. **Resolver.** `project_display_name_for("gh_acme__widgets")` → `"widgets"` when `PROJECT_NAME` set; returns the key
   unchanged when unset; cache invalidates on projects-dir mtime change.
5. **AXE description / panels.** Confirm-kill/rerun description and process-select description render the logical name;
   info-panel/dashboard render the logical name for a `BackgroundCommandInfo` whose `project` has a `PROJECT_NAME`.
6. **Command-history + prompt completion** render the logical name and fall back to the key when unset.

## Validation

Per repo rules for this ephemeral workspace: run `just install` first, then `just check` (lint + mypy + tests, including
the PNG visual snapshot suite). If a TUI PNG snapshot happens to pin a directory-key string in any touched surface,
accept the expected directory-key → logical-name swap with `--sase-update-visual-snapshots` only after confirming the
diff is exactly that swap.

## Risk Summary

- Lowest-risk class of change: display-only. Part A reads an already-cached field and adds no disk reads; Part B adds
  one mtime-cached records read shared across surfaces.
- The only non-trivial transform is the AGENT XPROMPT body rewrite (A2); it is constrained to VCS-ref patterns and to
  the agent's own directory key, so worst case is a cosmetic miss (key shown where the field was not populated), never a
  wrong substitution.
- Part A and Part B are independent; Part A alone fully resolves the screenshot if a smaller landing is preferred.

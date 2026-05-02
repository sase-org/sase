---
create_time: 2026-04-28 15:29:42
status: done
prompt: sdd/prompts/202604/dedup_agent_names_1.md
---

# Plan: Dedup agent names on revive and on explicit `%name:` claim

## Problem

The Agents-tab invariant — every visible agent has a distinct name — is broken (or recovered only by surprising
fallback) in two flows today:

1. **`R` revive** (`AgentRevivalMixin._do_revive_agent` → `_build_revive_name_map` → `allocate_revived_name` in
   `src/sase/agent/names/_auto.py:203`): strips the `YYmmdd.` dismissal prefix. When the stripped name is already in use
   by a visible agent (running or done-not-dismissed), the revived agent is given a fresh **alphabetic auto-name** (`a`,
   `b`, …) via `_next_available_name`. The user-meaningful base name is discarded for an arbitrary letter — jarring, and
   it loses the connection between the revived agent and its original identity.

2. **`%name:<name>` directive on launch** (`extract_directives_and_write_meta` → `claim_agent_name` in
   `src/sase/agent/names/_claim.py`): when a visible non-done agent already owns `<name>`, `claim_agent_name` **strips
   the `name` (and `workflow_name` if it matches) field** from the existing agent's on-disk metadata. The colliding
   agent silently becomes anonymous on the Agents tab. **Done agents are skipped entirely** — meaning a fresh
   `%name:foo` will land _next to_ an existing visible done `foo`, breaking the invariant outright.

In both cases the user wants the same fix: **append a numeric suffix `.2`, `.3`, …** to disambiguate. The direction of
the rename differs:

- **Revive**: rename the **incoming (revived)** agent — the user is reviving into a tab that already has a live `foo`,
  so the revived one becomes `foo.2`. The newer "claimer" is the existing live agent.
- **`%name:` claim**: rename the **existing** agent — the user explicitly asked for `foo`, so the existing agent (done
  or running) is demoted to `foo.2`, and the new launch keeps `foo` as written. The newer claimer is the launching
  agent.

## Goal

After this change:

- Reviving `260428.foo` while another visible `foo` exists yields `foo.2` (not `c`), with a notification that mentions
  the new name.
- Launching `%name:foo` while a visible `foo` (running OR done) exists keeps `foo` for the new launch and renames the
  existing agent to `foo.2` — both on disk and (via the existing dismissed-reference rewriter) in any `%wait:foo` /
  `#resume:foo` markers held by other agents.
- Bare `%name` (no explicit arg) and auto-generated names retain their current "best-effort cleanup of stale ghost
  names" behavior — they do **not** rename live agents, since that would surprise users who never asked for a specific
  name.

## What counts as "on the Agents tab"

The single source of truth is `get_active_agent_names()` in `src/sase/agent/names/_auto.py:33`. It enumerates names held
by:

- running non-done agents whose process is alive (`is_process_alive`), and
- any done agent that has not been dismissed (raw_suffix not in `_dismissed_suffixes`).

Both flows in this plan use that exact pool, so "on the Agents tab" is defined operationally and consistently. Workflow
children with `parent_timestamp` set reserve only their auto-name **prefix** (e.g. `m`), not the full child name
(`m.code`); we keep that behavior — children inherit the parent's rename via the workflow-name reservation, not via
walking the parent_timestamp tree.

## Proposed solution

### 1. Shared dedup helper

Add `dedup_name(base, reserved) -> str` to `src/sase/agent/names/_auto.py` (re-exported from `sase.agent.names`):

- Returns `base` if `base not in reserved`.
- Otherwise returns the lowest `f"{base}.{n}"` for integer `n ≥ 2` not in `reserved`.
- Mutates `reserved` in place with the chosen name (mirrors `allocate_revived_name`'s `reserved` contract for batch
  callers).

Numeric `<base>.<digit>` matches the existing repeat-batch convention (`a.1`, `a.2`, …) and the
`extract_auto_name_prefix` logic in `_common.py`, so it slots in without inventing new naming dialect. The `.<digit>`
form is also already recognized by `get_active_child_names` for child-slot reservation, which means dedup'd names are
correctly excluded from future auto-name allocation without further plumbing.

### 2. Revive flow — `dedup_name` instead of auto-name fallback

`src/sase/agent/names/_auto.py::allocate_revived_name`:

- Replace the `_next_available_name(pool)` fallback with `dedup_name(candidate, pool)`. The function signature stays
  `(allocated_name, fallback_original_or_None)` — the revive callsites already use the second element only to drive a
  notification, and they keep working.

`src/sase/ace/tui/actions/agents/_revive.py`:

- Update both notification strings (single-revive line 260, batch-revive line 345) from "assigned a new auto-name" to
  `f"Original name '{original}' was taken; revived as '{name_map[YYmmdd.original]}'"`. The revived `agent.agent_name` is
  already the new name post-`_build_revive_name_map`, and `name_map` already records the mapping; we just need to thread
  the new name into the warning. Concretely: change `unavailable: list[str]` to `unavailable: list[tuple[str, str]]`
  carrying `(fallback, allocated)` pairs, populated alongside the existing `agent.agent_name = new` assignment.

That covers the whole revive flow — `_build_revive_name_map` already mutates `agent.agent_name` in place;
`_restore_agent_artifacts` already writes the new name into `done.json`/`agent_meta.json`; and
`_apply_revive_reference_rewrites` already calls `rewrite_dismissed_references` with the same `name_map`, so any
`%wait:260428.foo` or `#resume:260428.foo` references are rewritten to point at the new live name (`foo.2` if dedup'd,
or `foo` otherwise).

### 3. `%name:` claim flow — rename existing agent instead of stripping

This is the larger change. Three coordinated edits:

**a. Distinguish explicit vs auto `%name`** — add `name_explicit: bool = False` to `PromptDirectives`
(`src/sase/xprompt/_directive_types.py`). Set it in the directive extractor when `%name:<arg>` is parsed with a
non-empty arg (also for the `%name(arg)` and `%name:` `` `arg` `` forms — the existing directive regex handles all three
uniformly via group 2/3). Bare `%name` without an arg, and auto-named agents (`SASE_REPEAT_NAME` env path, auto-name
allocation), leave the flag at `False`.

**b. Pipe the flag into `claim_agent_name`** — change the signature to
`claim_agent_name(name, claiming_dir, *, explicit: bool = False)`. The single caller in
`src/sase/axe/run_agent_phases.py:150` (and any test setups) gets `explicit=directives.name_explicit`. When `explicit`
is `False`, retain today's strip-on-conflict behavior verbatim (don't change anything — that path handles ghost-name
cleanup and shouldn't surprise auto-named flows).

**c. Rewrite the body for `explicit=True`**:

```
1. reserved = get_active_agent_names() - {name}      # claimer is taking `name`, free it from the pool
2. name_map = {}
3. for each artifact_dir under ~/.sase/projects/*/artifacts/ace-run/* (excluding claiming_dir):
     - skip if dismissed (raw_suffix in dismissed_suffixes)
     - load agent_meta.json
     - if data.get("name") == name OR data.get("workflow_name") == name:
         new_name = dedup_name(name, reserved)
         rewrite agent_meta.json: data["name"] -> new_name (and data["workflow_name"] -> new_name if matched)
         if done.json exists: rewrite its "name" field too (mirrors save path)
         name_map[name] = new_name
         (continue scanning — multiple existing collisions are possible across workflow_name vs name)
4. if name_map: rewrite_dismissed_references(name_map)  # rewrite %wait/#resume in other agents' markers
```

**Done agents are renamed**, not skipped. Rationale: the spec invariant ("every visible name is distinct") covers the
Agents tab, and done-but-not-dismissed agents _are_ on the tab. Skipping them violates the invariant the user is asking
us to enforce. The cost is that historical `#resume:foo` references in _other_ agents' artifacts now point at `foo.2`
instead of `foo` — but `rewrite_dismissed_references` updates those references in lockstep, so resolution still works. A
user who hand-types `#resume:foo` in a fresh prompt after the rename will resolve to whichever agent currently owns
`foo` (the new claimer) — which is exactly what `#resume` should do.

**Workflow children of a renamed parent**: out of scope for v1. If parent `foo` has children `foo.code`, `foo.q`, the
children retain their old names. `extract_auto_name_prefix` and child-slot reservation continue to work because
children's names start with `foo.`, which is now a legacy prefix. Visual mismatch (parent shown as `foo.2`, children
shown as `foo.code`) is acceptable; if user feedback bites, a follow-up can extend the rename loop to walk
`parent_timestamp == <renamed_parent_raw_suffix>` and prefix-substitute. Mark this as a `TODO` comment in the rewritten
`claim_agent_name` so the seam is discoverable.

**Best-effort error handling stays**: name reservation must never block agent launch. Wrap each artifact rewrite in its
own try/except and continue on failure, same as today's `_strip_name_from_json`.

### 4. Notification of the rename

The launching agent runs in `axe.run_agent_phases`, which has no TUI surface — the Agents tab will pick up the rename on
its next `_load_agents()` poll. We accept silent rename here: the user explicitly typed `%name:foo`, so seeing the old
`foo` become `foo.2` is the expected outcome, not a surprise warning. (If we later want a toast, we can post via
`~/.sase/notifications/*.json` from `claim_agent_name` — explicitly out of scope.)

## Edge cases considered

- **Multiple existing collisions**: scan loop allocates one suffix per conflict via the shared, mutable `reserved` set,
  so two stale `foo`s become `foo.2` and `foo.3` deterministically.
- **`workflow_name` vs `name` collision**: handled in the same branch — match either, rename both fields when the
  matched field is `workflow_name` (mirrors the existing `_strip_name_from_json` pairing logic for parent workflows).
- **Two-claimer race** (auto-naming): both claimers see the other's name as free during their own
  `get_active_agent_names` scan, both write `name=a`, both call `claim_agent_name(name="a", explicit=False)` — falls
  through to today's strip behavior, one ends up anonymous. We don't introduce locking; this is the same race as today.
- **`%name:` while parent agent is currently running** — fine. `agent_meta.json` is the live state file; rewriting it in
  place updates the visible name on the next `_load_agents()` refresh. Process is unaware.
- **Revive batch with two dismissed `foo`s** — first becomes `foo.2`, second becomes `foo.3` because `reserved` grows
  per allocation. Already correct via `_build_revive_name_map`'s shared-`reserved` loop; just verify by test.
- **Revive of a dismissed `foo` while live `foo` and live `foo.2` exist** — reserved = `{foo, foo.2}`, allocate yields
  `foo.3`. Correct by construction.
- **`extract_auto_name_prefix` interaction**: `foo.2` strips to `foo` for prefix reservation, so a fresh `foo` auto-name
  request would still see `foo` as taken. No regression.

## Out of scope

- Renaming workflow children to track parent rename (`foo.code` → `foo.2.code`). Marked TODO in `claim_agent_name`.
- Locking or transaction semantics for concurrent claims — best-effort only.
- New keymap or CLI surface; behavior change is invisible until a collision happens.
- Notification toast on `%name:` rename — silent for now.

## Files to touch

| File                                             | Change                                                                                                                                                                                                |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/agent/names/_auto.py`                  | Add `dedup_name`; switch `allocate_revived_name` fallback from `_next_available_name` to `dedup_name`.                                                                                                |
| `src/sase/agent/names/__init__.py`               | Re-export `dedup_name`.                                                                                                                                                                               |
| `src/sase/agent/names/_claim.py`                 | Add `explicit` kwarg; rewrite body for the `True` branch (rename instead of strip); call `rewrite_dismissed_references`. Add child-rename TODO.                                                       |
| `src/sase/xprompt/_directive_types.py`           | Add `name_explicit: bool = False` to `PromptDirectives`.                                                                                                                                              |
| `src/sase/xprompt/directives.py`                 | Set `name_explicit=True` in the extractor when `%name:<arg>` parses with a non-empty arg.                                                                                                             |
| `src/sase/axe/run_agent_phases.py`               | Pass `explicit=directives.name_explicit` to `claim_agent_name`.                                                                                                                                       |
| `src/sase/ace/tui/actions/agents/_revive.py`     | Update `unavailable` list shape and notification copy to mention the new dedup'd name.                                                                                                                |
| `tests/test_agent_names.py`                      | Cover `dedup_name`, revive fallback to `foo.2`, batch-revive sequential `foo.2`/`foo.3`.                                                                                                              |
| `tests/test_agent_names_extract.py` (or similar) | Cover explicit-vs-bare `%name` flag detection.                                                                                                                                                        |
| `tests/test_agent_names.py` (claim section)      | Cover explicit-claim rename of running and done conflicts, `workflow_name` collision, multi-conflict, reference rewrite via `rewrite_dismissed_references`, non-explicit path retains strip behavior. |

## Verification

1. Targeted tests:
   ```bash
   pytest tests/test_agent_names.py tests/test_agent_names_extract.py tests/test_dismissed_name_rewrites.py
   ```
2. `just check` — type, lint, full unit suite.
3. Manual smoke in `sase ace`:
   - Launch agent `a`. Dismiss it. Launch fresh `a`. `R`-revive the dismissed one → expect `a.2` with the new "revived
     as 'a.2'" notification.
   - Launch a long-running agent with `%name:foo`. While it runs, launch a second agent with `%name:foo` — refresh
     Agents tab; first agent shows as `foo.2`, second as `foo`.
   - Repeat above where the first agent is _done-not-dismissed_ (verify done agents are renamed too).
   - Have a third agent with `%wait:foo` queued before step 2; verify it ends up waiting on the right agent (the new
     `foo`) after the rename — `rewrite_dismissed_references` should keep `%wait:foo` pointing at the renamed-out party,
     since the rewrite map says `foo → foo.2`. **Open question for impl**: is that the user-intended target? The wait
     was queued referencing the original `foo`, so rewriting to `foo.2` is correct. Cover this in test.

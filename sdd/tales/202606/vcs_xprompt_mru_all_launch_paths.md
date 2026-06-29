---
create_time: 2026-06-29 10:39:23
status: done
prompt: sdd/prompts/202606/vcs_xprompt_mru_all_launch_paths.md
---
# Plan: Record the submitted VCS xprompt workflow to the MRU on every launch path

## Problem

When the user presses `<ctrl+p>` in the prompt input widget, the widget is pre-filled with a previously-used VCS xprompt
workflow (the most-recently-used entry, then older entries on repeat presses). After the user types a prompt and submits
it, the VCS xprompt workflow they just used is **not always** promoted to the front of the MRU history. As a result, the
next time they press `<ctrl+p>` on a fresh prompt, the workflow they just submitted is not shown first.

The desired behavior: the VCS xprompt workflow embedded in the most recently **submitted** prompt must become the
most-recently-used entry, so the next first `<ctrl+p>` surfaces it.

## How the MRU works today

- The MRU is an ordered list of VCS prefixes (e.g. `#gh:sase`, `#gh:my_changespec`) persisted to
  `~/.sase/vcs_xprompt_mru.json`, most-recent-first. Source: `src/sase/history/vcs_xprompt_mru.py`.
  - `record_vcs_xprompt_usage(prefix)` moves/inserts a prefix at the front (dedup + cap), dropping the implicit default
    and known-but-non-launchable project prefixes.
  - `load_launchable_vcs_xprompt_mru()` is what `<ctrl+p>` cycles over. It prunes, at cycle time, any entry that would
    no longer launch (implicit default, stale known project, or a ref whose target no longer resolves such as a
    submitted/archived changespec).
- `<ctrl+p>`/`<ctrl+n>` cycling reads the MRU via `load_launchable_vcs_xprompt_mru()`
  (`src/sase/ace/tui/widgets/_vcs_mru_cycling.py`). The first `<ctrl+p>` on an empty prompt always shows `mru[0]`.
- On submit, recording is performed by `record_resolved_vcs_xprompt_usage(vcs_ref, project_name)` in
  `src/sase/ace/tui/actions/agent_workflow/_launch_history.py`, which records `#{workflow_type}:{ref}` only after
  resolution proves the ref is reusable (the project that owns the ref must be launchable, or the workflow must be a
  non-workspace workflow such as `#cd`).

## Root cause

`record_resolved_vcs_xprompt_usage(...)` is invoked from **only one** place: the home-mode, single-launch resolution
branch of `_run_agent_launch_body` (`src/sase/ace/tui/actions/agent_workflow/_launch_body.py`, the call guarded by
`if vcs_ref is not None:` immediately after the home-mode VCS resolution block).

`_run_agent_launch_body` actually has **several** dispatch paths, and the VCS ref is detected independently in each one.
Recording was wired into only the first:

| Dispatch path                                                                                      | VCS ref variable                                          | Recorded to MRU today? |
| -------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | ---------------------- |
| Home-mode single launch (workflow-loop resolve **or** known-project fallback)                      | `vcs_ref`                                                 | **Yes**                |
| Home-mode same-segment model fan-out (`%{…}` / `%alt` / `#swarm`)                                  | `vcs_ref` (set in the home block before fan-out planning) | **Yes**                |
| Home-mode **multi-prompt** (`---` separators, or a multi-agent xprompt that expands to >1 segment) | `mp_vcs_ref`                                              | **No**                 |
| Non-home-mode launches (the bulk-launch entry point; also non-home fan-out)                        | `vcs_ref` detected by the separate non-home pattern scan  | **No**                 |

The multi-prompt branch detects `mp_vcs_ref` and even relabels the launch from it, then early-returns to queue the
multi-prompt agents — without ever calling the recorder. The non-home pattern scan likewise detects a `vcs_ref` purely
for workspace pre-allocation and never records it.

### Evidence

This was confirmed by exercising the real `_run_agent_launch_body` against the existing test harness
(`tests/ace/tui/_agent_launch_helpers.py`) with the MRU recorder patched and observed:

- Home-mode single launch with `#gh:<ref>` → `record_vcs_xprompt_usage("#gh:<ref>")` **is** called.
- Home-mode known-project fallback (`#gh:<project>`) → **is** called.
- Home-mode same-segment fan-out → **is** called.
- Home-mode multi-prompt (`#gh:<ref> … --- …`) → **not** called.
- Non-home-mode single / fan-out → **not** called.

So the user's symptom appears whenever the submitted prompt is dispatched as a **multi-prompt** (the reachable gap for
the interactive `<ctrl+p>` flow, since the interactive launch bar is always home-mode), and on the non-home (bulk) path.

## Goals

1. The VCS workflow in any successfully-dispatched, submitted prompt becomes the front of the MRU, so the next first
   `<ctrl+p>` surfaces it — regardless of whether the launch is single, multi-prompt, fan-out, home-mode, or non-home
   (bulk).
2. Preserve the existing reusability protection: never record the implicit default prefix, and never record a ref whose
   owning project is not launchable (the property covered by
   `test_run_agent_launch_body_does_not_save_non_launchable_resolved_vcs_ref`). The cycle-time pruning in
   `load_launchable_vcs_xprompt_mru()` remains the backstop for entries that go stale later.
3. Do not change `<ctrl+p>` cycling, the on-disk MRU format, or the home-mode single-launch behavior that already works.

## Approach

Make MRU recording a property of "a prompt was submitted and dispatched", not a property of one particular resolution
branch.

1. **Single recording chokepoint.** Funnel all recording through one helper (extend / wrap the existing
   `record_resolved_vcs_xprompt_usage`) so each dispatch path records the workflow it actually launched. Keep the helper
   responsible for the reusability guard so the rule lives in one place.

2. **Multi-prompt branch.** When the multi-prompt branch has detected a leading `mp_vcs_ref`, record it before the
   launch is queued (next to where the multi-prompt path already writes prompt history / file references). The recorder
   needs the **owning project** of the ref for its launchability guard — the multi-prompt branch currently sets only the
   display label from the ref, not `ctx.project_name`. Resolve the owning project the same way the home-mode single path
   does (reuse `_resolve_vcs_from_prompt(...)` for the ref's workflow type, which already returns the resolved owning
   project name) and pass that to the recorder.

3. **Non-home / bulk branch.** When the non-home pattern scan detects a `vcs_ref`, record it through the same helper
   with the ref's resolved owning project. (Bulk rejects multi-prompts, so this is a single-ref record.) This makes the
   MRU reflect non-home launches too; it is lower priority than the multi-prompt fix because it is not on the
   interactive `<ctrl+p>` path, but it closes the same class of gap and keeps the behavior uniform.

4. **Guard-correctness detail.** The home-mode single path passes `ctx.project_name`, which it has already set to the
   ref's owning project. The new call sites must pass the **ref's** owning project, not the baked context project (which
   in multi-prompt home mode is `home`). Getting this wrong would either over-record (defeating the non-launchable
   guard) or under-record (dropping valid entries), so the owning-project resolution is the crux of the change. Where
   the owning project genuinely cannot be resolved cheaply, prefer recording and letting
   `load_launchable_vcs_xprompt_mru()` prune at cycle time over silently dropping a workflow the user just used.

## Testing

- **New regression tests** (alongside `tests/ace/tui/test_agent_launch_vcs.py`, which already covers the home-mode
  single cases):
  - Home-mode multi-prompt launch with a leading VCS ref records `#{wf}:{ref}` exactly once and promotes it to the MRU
    front.
  - Non-home (bulk) launch with a VCS ref records it.
  - A multi-prompt / non-home launch whose owning project is **not** launchable does **not** record (mirror of
    `test_run_agent_launch_body_does_not_save_non_launchable_resolved_vcs_ref`).
- **Direct MRU unit check** (alongside `tests/test_vcs_xprompt_mru.py`): recording a non-front prefix moves it to
  `mru[0]` so the next `load_launchable_vcs_xprompt_mru()[0]` is that prefix — the literal "next `<ctrl+p>` shows it
  first" guarantee.
- **No regressions:** existing home-mode single-launch recording tests and the `<ctrl+p>` cycling tests
  (`tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py`, `tests/ace/tui/widgets/test_vcs_mru_cycling_logic.py`) keep
  passing.
- Run `just check`.

## Out of scope / non-goals

- No change to the cycling ring semantics, the terminal empty stop, or `<ctrl+n>` behavior.
- No change to the MRU file schema, location, or cap.
- No change to the unresolved-ref launch-abort guard (the existing `<ctrl+p>` desync protection for home-mode refs that
  no longer resolve).
- The broader VCS xprompt observability/hardening items in `sdd/research/202605/vcs_xprompt_hardening_research.md` are
  unrelated and not addressed here.

## Risks

- **Guard regression:** passing the wrong project to the launchability guard could re-introduce recording of
  non-launchable refs. Mitigated by the dedicated non-launchable test on the new paths.
- **Double recording:** a prompt that is both home-mode and multi-prompt must record exactly once. Mitigated by
  recording per dispatch path (the multi-prompt branch early-returns before the single-launch recorder) and asserting
  `called_once` in tests.

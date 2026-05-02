---
create_time: 2026-04-28 15:18:47
status: wip
prompt: sdd/prompts/202604/dedup_agent_names.md
---
# Plan: Dedup agent names on revive and on `%name:` claim

## Problem

Two flows currently risk producing duplicate names on the Agents tab — and one of them already detects the collision but
resolves it in a surprising way:

1. **`R` revive** (`AgentRevivalMixin._do_revive_agent` → `_build_revive_name_map` → `allocate_revived_name`): strips
   the `YYmmdd.` dismissal prefix. When the stripped name is already in use by another visible agent, the revived agent
   is given the **next free alphabetic auto-name** (`a`, `b`, …, `aa`, …). That's jarring — a user who revives `myplan`
   shouldn't suddenly see it relisted as `c`. The base name is meaningful and should be preserved.

2. **`%name:<name>` directive on launch** (`extract_directives_and_write_meta` → `claim_agent_name`): when an existing
   agent already owns `<name>`, `claim_agent_name` _strips_ the `name` (and `workflow_name` if matched) field from that
   agent's on-disk metadata. The colliding agent silently loses its identity instead of being renamed. The new agent
   claims `<name>` cleanly, but the existing one becomes anonymous on the Agents tab.

In both cases the user wants the same fix: when a name `foo` collides, append a numeric suffix to produce `foo.2`,
`foo.3`, … and pick the lowest free form. Direction of the rename differs:

- **Revive flow** dedups the **incoming (revived)** agent — the user is reviving into a tab that already has a live
  `foo`, so the revived one becomes `foo.2`.
- **`%name:` flow** dedups the **existing** agent — the user _explicitly_ asked the new agent to be `foo`, so the
  existing one is demoted to `foo.2` and the new launch keeps `foo` as written.

## Proposed solution

### One shared dedup helper

Add `dedup_name(base, reserved) -> str` to `src/sase/agent/names/_auto.py` (exported through `sase.agent.names`).
Returns `base` if free, else the lowest `f"{base}.{n}"` for `n ≥ 2` not in `reserved`. The `<base>.<digit>` form matches
the existing repeat-batch convention (`a.1`, `a.2`, …), so it slots in without inventing a new naming dialect.

### Change 1 — Revive uses dedup instead of fallback to auto-name

In `src/sase/agent/names/_auto.py::allocate_revived_name`:

- Replace the `_next_available_name(pool)` fallback with `dedup_name(candidate, pool)`.
- Keep the `(allocated, fallback)` return shape so the caller's notification still works; `fallback` is `candidate` (the
  original stripped name) when a suffix was needed, else `None`.

In `src/sase/ace/tui/actions/agents/_revive.py`:

- Reword the warning notification from _"Original name 'foo' was taken; assigned a new auto-name"_ to _"Original name
  'foo' was taken; revived as 'foo.2'"_. The map already records `old → new`, so the new name is available without
  re-querying.

That's it for Revive — `_build_revive_name_map` already mutates `agent.agent_name` in place and
`_restore_agent_artifacts` already writes the new name into `done.json` / `agent_meta.json`. No further plumbing needed.

### Change 2 — `claim_agent_name` renames the existing agent instead of stripping

Rewrite `src/sase/agent/names/_claim.py::claim_agent_name(name, claiming_dir)`:

1. Walk `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` (and `done.json`) the same way the current
   implementation does.
2. For each conflicting artifact dir (excluding `claiming_dir`):
   - **Skip done agents** (preserve current behavior — done agents need their identity for `#resume` / historical
     lookup).
   - For each conflicting _running_ agent, allocate a unique replacement via `dedup_name(name, reserved)`, where
     `reserved` is built from `get_active_agent_names()` _minus_ `name` itself (since we're freeing it for the claimer)
     and grows with each allocation in this loop.
   - Build a `name_map = {old_name: new_name}` (one entry per renamed agent).
   - Rewrite the `name` field in the conflicting `agent_meta.json` / `done.json` to `new_name` (instead of deleting it).
   - **`workflow_name` collision case**: when `data["workflow_name"] == name`, also rewrite `workflow_name` to
     `new_name`. This is sufficient for the parent to display correctly. Children still carry their original `name`
     (`foo.code`, `foo.q`, …) — those are written at child-launch time and don't re-derive from parent. Visual mismatch
     is acceptable for v1 and matches what the dismiss-rewrite flow already does (it doesn't follow children either). A
     follow-up ticket can extend dedup to walk `parent_timestamp` children if user feedback demands it.
3. After all on-disk renames: call `rewrite_dismissed_references(name_map)` (the same helper revive uses) so any
   `%wait:foo` / `#resume:foo` references in other agents' artifact markers and `raw_xprompt.md` files follow the
   rename. No in-memory agents to pass — `claim_agent_name` runs in the launching agent's process, not the TUI's.
4. Best-effort error swallowing stays — name reservation must never block agent launch.

### Notification

The launching agent has no TUI-visible notification surface. The TUI will pick up the rename on its next
`_load_agents()` refresh (already polled). We accept silent rename here — the user explicitly asked for `%name:foo`, so
seeing the old `foo` become `foo.2` is the expected outcome.

## Out of scope

- Renaming workflow children to track parent rename (`foo.code` → `foo.2.code`). Parents and children become visually
  disconnected after a `%name:` collision; if this turns out to bite, fix it by walking
  `parent_timestamp == <renamed_parent_ts>` and applying a consistent prefix swap. Mark as TODO in the rewritten
  `claim_agent_name`.
- Done agents are still excluded from rename. `#resume:foo` should keep pointing at the historical `foo`, and a fresh
  `%name:foo` claim shouldn't retroactively rename history.
- No new keymap or CLI surface. The behavior change is invisible until a collision happens.

## Files to touch

| File                                                     | Change                                                                                                                                                                                    |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/agent/names/_auto.py`                          | Add `dedup_name`; switch `allocate_revived_name` fallback from `_next_available_name` to `dedup_name`.                                                                                    |
| `src/sase/agent/names/__init__.py`                       | Re-export `dedup_name` (if other call sites want it).                                                                                                                                     |
| `src/sase/agent/names/_claim.py`                         | Rewrite `claim_agent_name` to rename instead of strip; call `rewrite_dismissed_references`. Drop `_strip_name_from_json` (or keep narrowly for the workflow_name-without-name edge case). |
| `src/sase/ace/tui/actions/agents/_revive.py`             | Update notification copy to mention the new `<base>.<n>` form.                                                                                                                            |
| `tests/agent/names/test_auto.py` (likely already exists) | Cover `dedup_name` plus the new `allocate_revived_name` fallback.                                                                                                                         |
| `tests/agent/names/test_claim.py` (rewrite)              | Cover rename-on-collision behavior, `workflow_name` collision, done-agent skip, reference rewrite via `rewrite_dismissed_references`.                                                     |

## Verification

1. `just check` — type, lint, unit tests.
2. Manual smoke test in `sase ace`:
   - Launch agent `a`. Dismiss it. Launch a fresh `a`. `R`-revive the dismissed one — confirm it appears as `a.2` with
     the warning notification.
   - Launch `%name:foo` while a running `foo` exists — confirm the running `foo` becomes `foo.2` on next refresh and the
     new agent owns `foo`.
   - Add a `%wait:foo` dependent before the second launch — confirm the dependent is rewritten to wait on `foo.2` (or
     `foo`, depending on which foo it intended to wait on; the rewrite should target the renamed one).

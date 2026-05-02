---
create_time: 2026-04-23 20:58:46
status: done
prompt: sdd/prompts/202604/repeat_fanout_name_collision_from_telegram.md
---
# Plan: Fix `%r:N` Name Collision When Launched via Telegram

## Problem

Sending `#gh_sase %r:3 #bd__next %a` (or any prompt containing `%r:N`) to the Telegram bot immediately errors out with

> Failed to launch agent: agent name 'q' would collide at 'q.2' — dismiss or wait for the existing agent, or pick a
> different base name

even on the very first attempt, with no live `q.*` agent running. Re-sending the same command picks a different letter
(`r`, `s`, …) and fails with the same shape of error. Single-agent launches (no `%r`) work fine.

## Root cause

Two cooperating issues:

1. **Telegram prepends `%n:<auto>` _unconditionally_.** `sase_tg_inbound._launch_single_agent`
   (`../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py:397-400`) always calls `get_next_auto_name()` and
   prepends `%n:<auto_name>` to the prompt before calling `launch_agent_from_cwd`, so the Telegram bot can show the user
   which name the agent got. That is correct for single-agent prompts but WRONG when the prompt also carries `%r:N`: the
   auto-generated name ceases to be implicit ("I don't care, pick any free one") and becomes an **explicit** base that
   the repeat launcher is required to honor.

2. **`get_next_auto_name()` does not consider child-named agents.** The scan at `src/sase/agent/names.py:460` only keys
   on `workflow_name or name` at the top level. A long-finished `%r:3` batch (named e.g. `q.1`, `q.2`, `q.3`) that the
   user never dismissed leaves three artifact dirs. Their `name` field is `q.<k>`, so `_get_active_child_names("q")`
   _does_ flag `q.*` as taken. But `_get_active_agent_names()` indexes on `workflow_name`, not on the derived base
   prefix `q`, so the letter `q` still looks free to the auto-sequence.

   Combining the two: Telegram asks `get_next_auto_name()` → it happily returns `q` (because `q` is not in the top-level
   set). Telegram prepends `%n:q`. `spawn_repeat_batch` now sees `explicit_base="q"` and calls
   `reserve_repeat_name_base("q", 3)`, which — correctly, per its strict design — scans child names, finds the orphan
   `q.2`, and raises `NameCollisionError`.

Evidence: the user's `~/.sase/projects/*/artifacts/ace-run/` tree contains **359 undismissed child-named agents**
(`f.2`, `q.2`, `r.2`, …) from batches dating back to March. Any Telegram `%r:N` invocation that lands on a letter with
one of these orphans as a child hits the collision.

Related but secondary: the same latent hazard exists in the pure TUI path (`_launch_repeat.py` → `spawn_repeat_batch`
with `%n` omitted): `reserve_repeat_name_base(None, count)` delegates to `get_next_auto_name()` and does **not**
re-check children, so a TUI-launched `%r:N` with no explicit `%n` can _silently_ produce two agents with the same
`<base>.<k>` name (one live, one orphan). No user-visible error, but artifact and telemetry confusion.

## Goal

After this plan lands:

1. `#gh_sase %r:3 #bd__next %a` sent to the Telegram bot launches three agents cleanly, named `<base>.1`, `<base>.2`,
   `<base>.3`, where `<base>` is a letter that has neither a live top-level claim nor any orphan child-named agent.
2. The TUI path (`sase ace` with `%r:3` and no `%n`) picks the same kind of conflict-free base automatically.
3. An explicit `%n:<base>` from the user still triggers the strict "fail loud" collision check — users who pick a
   specific name must dismiss first, per the design in `plans/202604/repeat_agents_as_entries.md` §5.
4. No behavior change for single-agent launches (no `%r`): Telegram's auto-name prepend path stays intact.

## Non-goals

- Not bulk-dismissing the 359 orphan artifacts. Dismissal is user-driven by policy; this plan makes the auto-name logic
  robust in their presence. (A follow-up "sweep stale child-named artifacts" CLI is reasonable but out of scope.)
- Not changing the `reserve_repeat_name_base` error message or the "fail loud for explicit base" contract.
- Not touching the `%r`/`%repeat` directive surface or the existing fan-out mechanics in `spawn_repeat_batch`.
- Not touching `_launch_repeat.py` — it calls `spawn_repeat_batch` without an explicit base in the no-`%n` case, and the
  fix lands one level below it in `names.py`.

## Design

### Fix 1 (primary, required) — teach the auto-name scan to respect child-name bases

**Location:** `src/sase/agent/names.py`, inside `_get_active_agent_names()` (lines ~417-484).

For each active agent whose `name` looks like `<prefix>.<digits>` (same shape as `_get_active_child_names`'s regex), add
the **prefix** to the returned set in addition to the current `workflow_name or name`. Concretely:

```python
name_field = data.get("name")
names.add(data.get("workflow_name") or name_field)
if isinstance(name_field, str):
    m = re.match(r"^([a-z]+)\.\d+$", name_field)
    if m:
        names.add(m.group(1))
```

Effect: `get_next_auto_name()` now skips any letter whose batch (live or merely undismissed) claims `<letter>.<k>` —
guaranteeing that the letter it returns is safe to use as a repeat base AND as a single-agent name.

The `parent_timestamp` skip and `is_process_alive` check remain in place for the existing paths; the new prefix is only
recorded when the existing filters already admit the agent into the scan. No change to the function signature, call
sites, or semantics for top-level names.

**Side benefit:** The TUI "silent overlap" latent bug also disappears — `reserve_repeat_name_base(None, N)` now gets an
auto base that provably has no child conflicts, so the no-`%n` repeat path is safe.

### Fix 2 (secondary, recommended) — Telegram: skip `%n:` prepend for `%r:N` prompts

**Location:** `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py:397-400`.

Before the auto-name prepend block, add a short-circuit: if the expanded prompt carries `%r` / `%repeat` with count

> 1, don't prepend `%n:<auto>`. Pass the raw prompt straight through to `launch_agent_from_cwd`, which will route it
> through `spawn_repeat_batch`, which owns naming for the batch.

```python
from sase.agent.repeat_launcher import extract_repeat_and_name

repeat_count, _, _ = extract_repeat_and_name(expanded)
is_repeat = repeat_count is not None and repeat_count > 1

auto_name: str | None = None
if directives.name is None and not is_repeat:
    auto_name = get_next_auto_name()
    prompt = f"%n:{auto_name} {prompt}"
```

The downstream "agent_name" label used in the Telegram reply needs an update for the repeat case — display `"repeat×N"`
(or similar) instead of `@<name>`, since there are now N names and they aren't known until after the spawn. The
batch-level `spawn_repeat_batch` return value (`list[RepeatAgentSpec]`) already carries the spawned names; prefer
surfacing them in a follow-up message if easily feasible, otherwise settle for the count in this plan and defer the
"show all N names" nicety.

Rationale for keeping Fix 2 even after Fix 1: Fix 1 makes Telegram's auto-name collision-free, so Fix 2 is no longer
required to unbreak the feature. But Telegram prepending `%n:<letter>` effectively **hides** which letter the repeat
launcher would have picked on its own, and it forces `reserve_repeat_name_base` into the strict-explicit path when the
user didn't actually ask for a specific name. Skipping the prepend keeps concerns separated: Telegram owns "single-agent
naming for the reply label"; `repeat_launcher` owns "batch naming." Small, local change.

### Fix 3 (optional, not in this plan) — auto-dismiss old child-named artifacts

Out of scope, but worth a follow-up bead: add an artifact retention policy (e.g. auto-dismiss after 30 days with
`done.json` and no user interaction) so the 359-orphan baseline doesn't grow unbounded. Not required to fix this bug.

## Files touched

- `src/sase/agent/names.py` — Fix 1. Add ~6 lines inside `_get_active_agent_names`.
- `tests/test_names_repeat.py` (or a new `tests/test_names_auto_name_child_aware.py`) — one new test:
  `test_get_next_auto_name_skips_letter_with_active_child`. Seed a tmp artifact tree with one `agent_meta.json` having
  `name="q.2"` and `done.json`; assert `get_next_auto_name()` returns `"a"` when `q` would otherwise be the only
  candidate, OR asserts it skips `q` if `a..p` are seeded as taken.
- `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py` — Fix 2. ~5-line branch.
- `../sase-telegram/tests/test_sase_tg_inbound_*.py` (existing file, find via rg) — add a test that a prompt with `%r:3`
  is forwarded to `launch_agent_from_cwd` **without** an inserted `%n:` prefix.

## Verification

- `just check` passes from this repo root and from the `sase-telegram` repo root.
- Unit tests above green.
- Manual smoke (the exact repro from the bug report):
  1. Confirm orphan `q.2` (or similar child-named agent) exists in `~/.sase/projects/sase/artifacts/ace-run/`.
  2. Send `#gh_sase %r:3 #bd__next %a` to the Telegram bot.
  3. Observe three agents launch with names `<x>.1`, `<x>.2`, `<x>.3` where `<x>` has no orphan children — no "would
     collide" error.
  4. Re-send the same command without dismissing the first batch; the second batch picks a different `<y>` (again,
     child-conflict-free) and launches successfully.
- Regression: send `#gh_sase Describe this repo` (no `%r`). Still gets a single `@<name>` reply from the Telegram bot.
- TUI regression: in `sase ace`, run `%r:3 foo` with no `%n`. Three top-level agents appear, none colliding with an
  existing orphan child name.

## Risks

- **Regex drift.** Fix 1 hard-codes `^([a-z]+)\.\d+$` to extract the base prefix. The existing `_get_active_child_names`
  at line 573 uses the same shape (`rf"^{re.escape(base)}\.\d+$"`). Keep these in lockstep — extract a module-level
  constant (`_CHILD_NAME_RE = re.compile(r"^([a-z]+)\.\d+$")`) and reuse it in both functions so a future change to the
  naming scheme only touches one place.
- **Bases like `sase-z`.** Explicit user bases can be multi-segment (`sase-z.2`). The current auto-name sequence only
  emits `[a-z]+`, so Fix 1's prefix regex intentionally stays narrow — we do not want `sase-z.2` to reserve the string
  `sase-z` in the auto-set (it's not a reachable auto-name anyway, and `_get_active_agent_names` already records
  `sase-z` via the `workflow_name` path for active batches). Document this in a comment.
- **Performance.** The scan already walks every artifact dir and parses JSON per call; adding one regex match per agent
  is negligible. No new I/O. Still, `get_next_auto_name()` is hit on every Telegram submission and every TUI launch — if
  it shows up in profiles, memoize per-process with a short TTL (separate concern; not required now).
- **Telegram reply label for repeats.** Fix 2 changes what the bot says in the confirmation message for repeat launches
  (no more `@<name>` line). Keep the change minimal — show `started N repeat agents` or equivalent — and note it in the
  PR description as a visible-but-intentional UX change. If the user prefers the old `@<name>` line with the base
  letter, wire `spawn_repeat_batch`'s return value back into the confirmation (small extra work, can be a follow-up).

## Out of scope

- Cleaning up the 359 existing orphan artifacts (see Fix 3 note).
- Any change to `reserve_repeat_name_base`'s "fail loud on explicit base" contract.
- Any change to how `%n:<base>.<k>` is re-injected into per-slot prompts by `spawn_repeat_batch`.
- Renaming or consolidating `_get_active_agent_names` vs `_get_active_child_names` (they have different use cases — the
  split is correct).

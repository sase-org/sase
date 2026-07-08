---
create_time: 2026-07-08 02:47:05
status: done
---
# Plan: Relaunch failed/waiting Fable epic-lander agents on Opus

## Problem

Fable usage credits are exhausted. Three SASE agents in the `gh_sase-org__sase` project are configured to run on the
Fable model and are stuck as a result. All three are **epic-lander** agents (`#bd/land_epic:<epic>`), and all three
select their model via the `%model:@epic_lander` alias, which resolves to `claude-fable-5` (defined in
`~/.config/sase/sase.yml`).

The two FAILED agents died with:

```
You're out of usage credits. Run /usage-credits to keep using Fable 5 or /model to switch models.
```

We want to kill the one that is still live and waiting, then relaunch all three using the **exact same prompts** they
were originally launched with, changing **only** the model from Fable to Opus.

## Target agents

| Agent     | Status  | Model (alias)                     | Waits on                   | Phase-bead state                           |
| --------- | ------- | --------------------------------- | -------------------------- | ------------------------------------------ |
| `sase-5l` | WAITING | `claude-fable-5` (`@epic_lander`) | `sase-5l.1` … `sase-5l.14` | `.1`/`.2` done, `.3` running, rest waiting |
| `sase-5k` | FAILED  | `claude-fable-5` (`@epic_lander`) | `sase-5k.1` … `sase-5k.4`  | all 4 DONE                                 |
| `sase-5j` | FAILED  | `claude-fable-5` (`@epic_lander`) | `sase-5j.1` … `sase-5j.6`  | all 6 DONE                                 |

Confirmed via `sase agent list -a -j` and each agent's `error_report.md` / `raw_xprompt.md` under
`~/.sase/projects/gh_sase-org__sase/artifacts/ace-run/`.

- Only `sase-5l` is live (WAITING) and therefore needs to be killed. `sase-5k` and `sase-5j` are already terminal
  (FAILED) — no kill required, only relaunch.
- The phase-worker beads these landers depend on run on `codex/gpt-5.5` / `opus` (not Fable), so they are unaffected and
  are **out of scope**.

## Goal / scope

- **In scope:** kill the live waiting Fable agent (`sase-5l`); relaunch `sase-5l`, `sase-5k`, `sase-5j` on Opus with
  byte-identical prompts except the model directive.
- **Out of scope:**
  - Phase-worker agents (`sase-5*.N`) — leave running/completed as-is.
  - The `@epic_lander` config alias in `~/.config/sase/sase.yml` — do **not** edit it. Changing the alias would silently
    repoint _future_ epic-lander launches too; instead we swap the model directive inline in each relaunch prompt only.
    (Config/memory files also require explicit user permission.)
  - Any source-code changes.

## Model directive change

Each original prompt contains the single line:

```
%model:@epic_lander
```

Replace **only** that line with:

```
%model:claude/opus
```

Everything else in each prompt (the `#gh:` workspace ref, `%name`, `%group`, `%auto:tale`, the `%w:` wait list, and
`#bd/land_epic:<epic>`) stays exactly as originally launched. Preflight confirmed `%model:claude/opus` resolves to
`CLAUDE(opus)` and that `#bd/land_epic:sase-5k` expands cleanly with no stray directives via `sase xprompt expand`.

## The three relaunch prompts (verbatim, model swapped)

**sase-5l**

```
#gh:gh_sase-org__sase
%name:sase-5l
%group:sase-5l
%model:claude/opus
%auto:tale
%w:sase-5l.1,sase-5l.2,sase-5l.3,sase-5l.4,sase-5l.5,sase-5l.6,sase-5l.7,sase-5l.8,sase-5l.9,sase-5l.10,sase-5l.11,sase-5l.12,sase-5l.13,sase-5l.14
#bd/land_epic:sase-5l
```

**sase-5k**

```
#gh:gh_sase-org__sase
%name:sase-5k
%group:sase-5k
%model:claude/opus
%auto:tale
%w:sase-5k.1,sase-5k.2,sase-5k.3,sase-5k.4
#bd/land_epic:sase-5k
```

**sase-5j**

```
#gh:gh_sase-org__sase
%name:sase-5j
%group:sase-5j
%model:claude/opus
%auto:tale
%w:sase-5j.1,sase-5j.2,sase-5j.5,sase-5j.6,sase-5j.3,sase-5j.4
#bd/land_epic:sase-5j
```

(Each is copied from that agent's `raw_xprompt.md`; the only edited byte is the `%model:` line.)

## Execution steps

1. **Re-verify current state** immediately before acting (statuses can drift):

   ```bash
   sase agent list -a -j | \
     python3 -c "import json,sys;[print(r['name'],r['status'],r['model']) for r in json.load(sys.stdin) if r['name'] in ('sase-5l','sase-5k','sase-5j')]"
   ```

   Expect `sase-5l WAITING`, `sase-5k FAILED`, `sase-5j FAILED`. If `sase-5l` has since completed or already failed,
   drop the kill step for it.

2. **Kill the live waiting Fable agent** (`sase-5l` only):

   ```bash
   sase agent kill -n sase-5l
   ```

   Then confirm it is terminal:

   ```bash
   sase agent list -a -j | \
     python3 -c "import json,sys;[print(r['name'],r['status']) for r in json.load(sys.stdin) if r['name']=='sase-5l']"
   ```

   Killing the lander does **not** touch its phase workers (`sase-5l.*`); they keep running.

3. **Preflight each relaunch prompt** (read-only) before requesting a launch:

   ```bash
   sase xprompt expand '<relaunch prompt>'
   ```

   It must succeed and report only the intended directives/references.

4. **Relaunch each agent on Opus via the `/sase_run` skill** (one `LaunchApproval` per agent — do NOT call `sase run`
   directly). For each of the three prompts, write a request file and submit:

   ```json
   {
     "schema_version": 1,
     "prompt": "<one of the three relaunch prompts above>",
     "reason": "Relaunch Fable epic-lander <name> on Opus; Fable credits exhausted.",
     "approval": "required",
     "max_slots": 1
   }
   ```

   ```bash
   sase launch request -f launch_request.json -o json
   ```

   Then poll the returned `response_file` for `launch_response.json` and only proceed on `"action": "approve"`,
   `"dispatch_status": "launched"`. If a request is rejected, do not spawn anyway — revise per the feedback.

   Order: relaunch `sase-5l` first (after its kill is confirmed terminal), then `sase-5k`, then `sase-5j`.
   `sase-5k`/`sase-5j` will find their waits already satisfied (all child beads DONE) and proceed to land immediately;
   `sase-5l` will park on its still-in-progress phase beads exactly as before.

## Name-reuse handling (known risk)

Each relaunch reuses the original `%name:` (`sase-5l` / `sase-5k` / `sase-5j`), which already exists in the agent-name
registry from the killed/failed run. SASE normally expects a _fresh_ retry name and reserves same-name reuse for
explicitly-approved reruns.

- **Primary path:** submit with the plain `%name:<name>` shown above. Because the prior runs are terminal (failed) or
  will be killed to terminal before relaunch, and because this is a user-requested, approval-gated rerun of those exact
  agents, same-name reuse is the intended outcome.
- **Fallback if dispatch is rejected for a name collision:** change that one prompt's `%name:<name>` to the forced-reuse
  form `%name:!<name>` (same name, just authorizing reuse of the now-terminal name) and resubmit. This is justified here
  as an explicitly-approved rerun; it keeps the name, group, wait list, and epic identical.
- Do **not** invent a different display name — these landers are meant to carry the epic's own id.

## Verification (after relaunch)

```bash
sase agent list -a -j | \
  python3 -c "import json,sys;[print(r['name'],r['status'],r['model'],r['provider']) for r in json.load(sys.stdin) if r['name'] in ('sase-5l','sase-5k','sase-5j')]"
```

Success looks like all three now showing `provider=claude`, `model=opus`, with `sase-5k`/`sase-5j` RUNNING (or DONE) and
`sase-5l` WAITING or RUNNING — none left on `claude-fable-5`, none FAILED on a credits error.

## Risks & rollback

- **Opus spend:** relaunching three epic landers on Opus consumes Opus credits. This is the explicit intent; nothing to
  mitigate beyond awareness.
- **Killing `sase-5l`:** interrupts only the idle waiting lander, not its phase workers. The relaunched Opus lander
  re-waits on the same beads, so no landing work is lost.
- **Rollback:** if a relaunch misbehaves, `sase agent kill -n <name>` stops it; the epic beads and phase-worker output
  are untouched, so a further relaunch is always possible.

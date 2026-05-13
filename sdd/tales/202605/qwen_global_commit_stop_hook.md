---
create_time: 2026-05-12 20:02:32
status: done
prompt: sdd/prompts/202605/qwen_global_commit_stop_hook.md
---
# Plan: Wire `sase_commit_stop_hook` into the Qwen Code runtime (global-first)

## Symptom

The `ru` agent (Qwen, `qwen3.6-plus`) ran on 2026-05-12 19:30:37 in `sase_100/` (see
`/home/bryan/.sase/projects/sase/artifacts/ace-run/20260512193037/agent_meta.json`). Its `done.json` `step_output._raw`
concluded "no action is needed" — but the agent had actually privatized `workspace_claim_request_from_dict` (eventually
landed in commit `1d4c1b610`).

`~/.sase_commit_stop_hook.jsonl` has zero records with `runtime: "qwen"`. The `ru` session (`20260512193037`) appears
nowhere in the log. The post-completion commit stop hook **never ran at all** for this agent — it didn't just dedup or
skip, the Qwen process had no hook to invoke.

This violates the "Uniform Agent Runtimes" rule in `memory/short/gotchas.md`: Claude, Gemini, Codex, and Qwen should all
participate in the commit stop hook the same way.

## Root Cause

Three concrete gaps, in priority order:

1. **No global Qwen hook registration in chezmoi.** Claude and Gemini both register `sase_commit_stop_hook` globally via
   chezmoi:
   - `~/.local/share/chezmoi/home/dot_claude/settings.json` → `hooks.Stop` → `sase_commit_stop_hook`
   - `~/.local/share/chezmoi/home/dot_gemini/settings.json.tmpl` → `hooks.AfterAgent` → `sase_commit_stop_hook`
   - `~/.local/share/chezmoi/home/dot_qwen/settings.json` has **no `hooks` key at all**. So `~/.qwen/settings.json`
     (which the user manages globally and which Qwen Code reads) never tells Qwen Code to run anything when an agent
     finishes. This is the primary user-flagged gap: the global hook is the one that runs across every repo, not just
     sibling-aware ones.

2. **No project-level Qwen hook registration in the repo.** Claude and Gemini have parallel checked-in
   `.claude/settings.json` and `.gemini/settings.json` that point at the repo-aware
   `tools/sase_sibling_commit_stop_hook` (sibling-repo dirty-tree check on top of the generic global hook). There is no
   `.qwen/` directory in the sase repo. Even after we add the global hook, sibling repo coverage for Qwen sessions will
   silently regress versus Claude/Gemini.

3. **The shared hook script doesn't know Qwen exists at runtime.** Both `src/sase/scripts/sase_commit_stop_hook.py` and
   `tools/sase_sibling_commit_stop_hook`:
   - Detect only `CODEX_THREAD_ID`/`CODEX_CI` and `GEMINI_PROJECT_DIR`. Qwen's project env var (`QWEN_PROJECT_DIR`, or
     `GEMINI_PROJECT_DIR` if Qwen Code inherits it as a Gemini fork — confirm during implementation) is unhandled.
   - `_resolve_project_dir()` doesn't consider any Qwen env var, so `os.getcwd()` is the fallback — fine when Qwen is
     launched in the workspace cwd, but not contractually safe.
   - `_emit_block()` only branches on Codex/Gemini and otherwise emits the Claude default (stderr + exit 2). If Qwen's
     accepted hook-output schema differs from Gemini's, the block won't be honored.
   - The `runtime` label in the structured log only takes values `claude` / `gemini` / `codex`, so a wired-up Qwen run
     would mislabel its log records.

Each gap on its own is sufficient to explain the `ru` failure. Gap 1 is what the user explicitly called out; gaps 2 and
3 must be closed at the same time or the global hook is still partially broken (no sibling-repo check, and possibly no
enforceable block).

## Goal

A Qwen agent that edits files but answers "no action needed" must reliably trigger `sase_commit_stop_hook`, producing a
`runtime: "qwen"` `script_start` + `block_emitted` (or `session_dedup_skip` on repeat) in
`~/.sase_commit_stop_hook.jsonl`, and the resulting follow-up turn or denial must prompt the agent to commit via
`/sase_git_commit`. This must hold both inside the sase repo (sibling-aware path) and outside it (global path only).

## Scope and Non-Scope

In scope:

- Global Qwen hook wiring in the chezmoi repo (the primary user ask).
- Project-level Qwen hook wiring in the sase repo, parallel to `.claude/`/`.gemini/`.
- Runtime detection + log labeling + emit-block schema for Qwen in both `sase_commit_stop_hook.py` and
  `sase_sibling_commit_stop_hook`.
- Tests for the new Qwen runtime branch.
- Doc note in `docs/llms.md` § Qwen Code Integration and a one-line update to `memory/long/llm_provider_hooks.md`
  recording the hook event Qwen uses.
- Running `just check` here and in the chezmoi repo, plus `chezmoi apply --force` after the chezmoi commit, per
  `memory/long/external_repos.md`.

Out of scope:

- A Codex-style in-band Python fallback in `QwenProvider.invoke()`. We are deliberately preferring the native hook
  because Qwen Code (a Gemini fork) documents hook support; the in-band fallback only belongs here if Step 1 of
  implementation reveals Qwen doesn't actually fire the configured hook in our `--yolo` stream-json mode.
- Touching `opencode`. Its commit-stop-hook story has its own gap and deserves a separate plan.
- Reworking `tools/sase_sibling_commit_stop_hook`'s sibling-repo discovery; only the runtime-detection and emit-block
  schema branches need to be Qwen-aware.

## Approach

### Step 1 — Verify Qwen actually fires a configured hook in `--yolo` stream-json mode

Before changing any user-visible config, run a one-shot probe:

- Temporarily add `~/.qwen/settings.json` `hooks.AfterAgent` (or `Stop` — try both if needed) with a
  `touch /tmp/sase_qwen_hook_probe` command.
- Launch a trivial Qwen agent (`sase run %model:qwen/qwen3-coder-flash 'echo hi'` or equivalent) and confirm the marker
  file appears and the standard hook-stdin JSON shape (`session_id`, `stop_hook_active`) is piped to the hook command.
  Note which env vars Qwen exports (`QWEN_PROJECT_DIR`? `GEMINI_PROJECT_DIR`?).
- Revert the temporary `~/.qwen/settings.json` change.

If the probe fails, stop and reopen this plan with the fallback path described under "Conditional fallback" below.

### Step 2 — Add the global hook in chezmoi (the user's primary ask)

Edit `~/.local/share/chezmoi/home/dot_qwen/settings.json` to add a top-level `hooks` block mirroring the Gemini
template's event and timeout choice, e.g.:

```json
"hooks": {
  "AfterAgent": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "sase_commit_stop_hook",
          "timeout": 60000
        }
      ]
    }
  ]
}
```

(Replace the event name with whatever Step 1 confirms.)

After the change: commit in the chezmoi repo using the commit skill, run `just check` there, then
`chezmoi apply --force` so `~/.qwen/settings.json` picks it up.

### Step 3 — Add the project-level hook in the sase repo

Create a new tracked `.qwen/settings.json` mirroring `.gemini/settings.json`:

```json
{
  "hooks": {
    "AfterAgent": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$QWEN_PROJECT_DIR\"/tools/sase_sibling_commit_stop_hook",
            "timeout": 60000
          }
        ]
      }
    ]
  }
}
```

If Step 1 shows Qwen Code exports `GEMINI_PROJECT_DIR` instead of `QWEN_PROJECT_DIR`, use that — pin whichever variable
is observed. Since the file is checked in, ephemeral `sase_<N>` workspaces inherit it through the normal clone, with no
extra deploy plumbing.

### Step 4 — Teach `sase_commit_stop_hook.py` about Qwen

In `src/sase/scripts/sase_commit_stop_hook.py`:

- Add `_is_qwen_runtime()` keyed on the env var Step 1 confirms.
- Extend `_resolve_project_dir()` to include the Qwen project-dir env var.
- Extend `_emit_block()` with a Qwen branch. If Qwen-as-Gemini-fork uses the same `{"decision": "deny", "reason": …}`
  shape, merge with the Gemini branch under a "gemini-family" predicate; otherwise add a separate branch.
- Update the dedup branch `runtime == "gemini" and hook_input.get("stop_hook_active")` to also fire for Qwen when it
  emits the same flag.
- Update the `runtime = "gemini" if ... else "codex" if ... else "claude"` ladder to include a `qwen` branch so log
  records label it correctly.

### Step 5 — Teach `tools/sase_sibling_commit_stop_hook` about Qwen

Parallel edits in the bash wrapper:

- Add `is_qwen_runtime` and a Qwen emit branch in `emit_block` (or fold into the Gemini branch if the output contract is
  identical).
- Add the Qwen project-dir env var to `resolve_project_dir`'s loop.
- The header comment already mentions Qwen — leave it, but make the code paths match.

### Step 6 — Tests

- Extend `tests/test_commit_stop_hook.py` with Qwen-runtime parametrizations of the existing Claude/Gemini/Codex test
  cases: project-dir resolution, emit-block JSON shape, dedup branch.
- Add a `tests/test_sibling_commit_stop_hook.py` parametrization for the Qwen runtime emit path.
- Add a simple file-existence assertion for `.qwen/settings.json` parallel to whatever guards
  `.claude/settings.json`/`.gemini/settings.json` today (or a new module if none exists).

### Step 7 — Docs and memory

- Add a short "Stop hook" subsection to `docs/llms.md` § Qwen Code Integration describing where the hook is registered
  (chezmoi global + repo project-level) and which event Qwen Code fires.
- Append a one-line entry to `memory/long/llm_provider_hooks.md` naming the Qwen hook event and env var observed in Step
  1, so future agents don't repeat this investigation. (Memory file changes require user approval per `AGENTS.md`.)

### Conditional fallback (only if Step 1 fails)

If the Step 1 probe shows Qwen doesn't fire hooks in `--yolo` stream-json mode, fall back to a Codex-style in-band turn
in `QwenProvider.invoke()`:

- Import `build_commit_details`, `native_marker_path`, `jlog` from `sase.scripts.sase_commit_stop_hook`.
- Wrap the final `return InvokeResult(...)` in a single follow-up turn that re-prompts Qwen with the commit-instruction
  block when the worktree is dirty, gated by the `SASE_AGENT_TIMESTAMP` one-shot marker.
- Log under `qwen_fallback_block_emitted` / `qwen_fallback_skip` to the same JSONL.

Only reach for this if native hooks really don't work; it costs an extra LLM turn and duplicates plumbing the Codex
provider already carries.

## Verification Checklist

1. Reproduce the `ru` failure mode: run a Qwen agent that edits a tracked file but answers "no action needed". Confirm
   `~/.sase_commit_stop_hook.jsonl` gains a fresh record with `runtime: "qwen"` and either `block_emitted` (native) or
   `qwen_fallback_block_emitted` (fallback).
2. The Qwen transcript shows a follow-up turn or denial mentioning `/sase_git_commit` and the changed files.
3. Inside the sase repo, also verify sibling dirty-tree detection still fires when one of the `../sase-*/` repos is
   dirty during a Qwen session.
4. `just check` passes here and in the chezmoi repo. `chezmoi apply --force` has been run after the chezmoi commit.

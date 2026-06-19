# Gemini CLI Failures → Antigravity CLI Migration

**Date:** 2026-06-19
**Author:** Research (agent-assisted)
**Status:** Confirmed root cause; recommendation pending decision

---

## TL;DR

Your hypothesis is correct. The `gemini` runtime is failing because **Google retired the
free / individual tier of Gemini CLI on June 18, 2026** (one day before this writing) and is
redirecting users to its new **Antigravity** product. The CLI binary is still installed and
runs, but the backend now rejects the client with an `IneligibleTierError` /
`UNSUPPORTED_CLIENT` error. The official replacement is the **Antigravity CLI**, invoked as
**`agy`**.

This is **not a drop-in swap.** The flags, command name, auth flow, and — most importantly —
the machine-readable output contract differ. The single biggest open risk for SASE is whether
`agy` can emit a streaming, parseable output format equivalent to Gemini CLI's
`--output-format stream-json`, because our entire Gemini parser depends on it.

---

## 1. The failure, reproduced

The `gemini` binary is still present and reports `0.35.0`:

```
$ which gemini
/home/bryan/.config/nvm/versions/node/v22.14.0/bin/gemini
$ gemini --version
0.35.0
```

Re-running it with the exact flags SASE uses (`src/sase/llm_provider/gemini.py`) reproduces the
failure:

```
$ printf 'say hi' | gemini --output-format stream-json --yolo --model gemini-3-flash-preview
Loaded cached credentials.
Error authenticating: IneligibleTierError: This client is no longer supported for
Gemini Code Assist for individuals. To continue using Gemini, please migrate to the
Antigravity suite of products: https://antigravity.google.
  ...
  ineligibleTiers: [
    {
      reasonCode: 'UNSUPPORTED_CLIENT',
      reasonMessage: 'This client is no longer supported for Gemini Code Assist for
        individuals. To continue using Gemini, please migrate to the Antigravity suite
        of products: https://antigravity.google.',
      tierId: 'free-tier',
      tierName: 'Gemini Code Assist for individuals'
    }
  ]
...
An unexpected critical error occurred: Error: This client is no longer supported for
Gemini Code Assist for individuals...
```

### Root cause

- The credentials are still cached and valid (`Loaded cached credentials`) — this is **not** an
  expired-token / re-login problem.
- The failure is **server-side authorization**: Google's `code_assist/setup` endpoint now returns
  `UNSUPPORTED_CLIENT` for `tierId: free-tier` ("Gemini Code Assist for individuals").
- The error message itself names the fix: *"migrate to the Antigravity suite of products."*
- This matches Google's announced shutdown date of **June 18, 2026** exactly — today is June 19, so
  the failures "starting recently" line up precisely.

No re-authentication, version bump, or config change to the existing `gemini` CLI will fix this for
an individual/free account — the product has been withdrawn for that tier.

---

## 2. Confirmation: Gemini CLI deprecation timeline

Announced at Google I/O on **May 19, 2026**; standalone Gemini CLI and the Gemini Code Assist IDE
extensions are being consolidated under the **Antigravity** brand.

| Item | Detail |
|------|--------|
| Shutdown date | **June 18, 2026** |
| Affected | Free tier, Google AI Pro/Ultra subscribers, Gemini Code Assist *for individuals*, Gemini Code Assist for GitHub (new installs blocked immediately) |
| **Not** affected | Enterprise customers on a **Gemini Code Assist Standard / Enterprise** license — `gemini` CLI keeps working with continued model access and updates |
| Replacement | **Antigravity CLI** (`agy`) — same agent harness as the Antigravity 2.0 desktop app |
| Migration docs | `antigravity.google/docs/gcli-migration` |

The most important migration action Google calls out: *find every place scripts/pipelines invoke
`gemini` and update them before the deadline.* For SASE that place is the `gemini` LLM provider
plugin.

---

## 3. What Antigravity CLI is

- **Command name:** `agy` (not `antigravity`, not `gemini`).
- **Built in Go** (the old Gemini CLI was Node/TypeScript), pitched as faster and able to orchestrate
  multiple background subagents.
- **Powered by Gemini models** (with optional Claude / open-source backends), same model family
  (e.g. `gemini-3.1-pro`, `gemini-3-flash`).
- **Install (macOS/Linux):**
  ```
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  ```
  Drops the `agy` binary into `~/.local/bin/` (per current docs). Available to everyone, including
  the free tier.
- **Auth:** via the Antigravity product; free-tier individuals are eligible (this is the supported
  path now that Gemini CLI's free tier is gone).

### Non-interactive contract (what SASE actually needs)

SASE drives the runtime headlessly — prompt on stdin, parse a streamed JSON event stream. The `agy`
flags reported by hands-on guides:

| Purpose | Gemini CLI (today) | Antigravity CLI (`agy`) |
|---------|--------------------|--------------------------|
| Binary | `gemini` | `agy` |
| Non-interactive prompt | prompt via **stdin** | `-p` / `--print "<prompt>"` |
| Model | `--model <name>` | `-m <name>` |
| Auto-approve tools (yolo) | `--yolo` | `--dangerously-skip-permissions` |
| Streaming/JSON output | `--output-format stream-json` | **⚠ UNCONFIRMED** — see below |
| Resume conversation | (none; context re-injected manually) | `-c` / `--continue`, `--conversation <id>` |

> **⚠ Critical unknown — output format.** Sources conflict: one hands-on guide shows an
> `--output-format json` example, but it does **not** appear in that build's `--help`. Whether `agy`
> can emit a stable, machine-parseable **streaming JSON** event stream equivalent to Gemini CLI's
> `stream-json` is the make-or-break question for this migration. If it cannot, the parser in
> `_subprocess_gemini.py` must be rewritten (or we fall back to non-streamed text via `-p`, losing
> incremental output, tool-call artifacts, and usage accounting).
>
> Interestingly, `agy` natively supports `-c`/`--conversation` resume, which could replace the
> manual context-reconstruction hack SASE currently does (`gemini.py:195-200`, "Gemini has no
> session persistence").

---

## 4. Impact on this codebase

The Gemini integration is a Python subprocess plugin (presentation/glue, not Rust-core logic — see
`memory/rust_core_backend_boundary.md`), so the change stays in this repo. Touchpoints:

| File | What needs to change |
|------|----------------------|
| `src/sase/llm_provider/gemini.py:19` | Default model `gemini-3-flash-preview`; confirm model names/aliases still valid under `agy`. |
| `src/sase/llm_provider/gemini.py:22-24` | `_gemini_bin()` resolves `SASE_GEMINI_PATH` or `gemini` → needs to point at `agy`. |
| `src/sase/llm_provider/gemini.py:~243-264` | Invocation: builds `gemini --output-format stream-json --yolo --model <m>`, writes prompt to **stdin**. Must become `agy -p <prompt> -m <m> --dangerously-skip-permissions [output flag]`. Note `agy` takes the prompt via `-p`, **not stdin** — this changes how the prompt is passed. |
| `src/sase/llm_provider/_subprocess_gemini.py` | The `stream_and_parse_gemini_json_output` parser is built around Gemini's `stream-json` event schema. Highest-risk file — depends entirely on the output-format answer above. |
| `src/sase/llm_provider/gemini.py:195-201` | Manual session/context reconstruction could be replaced by `agy`'s native `--continue`/`--conversation`. |
| `src/sase/doctor/checks_providers.py:31-35` | Setup hint still says `npm install -g @google/gemini-cli` + "run `gemini`". Must point to the `agy` installer and auth flow. |
| `pyproject.toml` (entry point `gemini = ...`) + `registry.py` | Decide: rename/replace the provider as `antigravity`/`agy`, or keep the `gemini` provider name but back it with `agy`. |

### Gotcha: `sase doctor` will NOT catch this

`sase doctor` is read-only and explicitly **does not call provider APIs**
(`checks_providers.py:48-50`, "auth: not verified"). Because the `gemini` binary is still on PATH and
executable, doctor reports the provider as **OK / executable found** even though every real run fails
with `IneligibleTierError`. Anyone relying on `sase doctor` to flag this will be misled. Worth a
follow-up: doctor could special-case a known dead-tier signature, or a `--deep` auth probe could be
added.

### Uniform-runtime constraint

Per `memory/gotchas.md` ("Uniform Agent Runtimes"), whatever we do must keep Gemini/Antigravity at
parity with Claude/Codex (hooks, skills, commit workflow). The `agy` harness has its own subagent and
skill model — confirm it still satisfies SASE's hook/skill/commit contract before committing to it as
the runtime.

---

## 5. Recommended next actions

**Immediate (today) — stop the bleeding:**

1. Stop defaulting to / autodetecting `gemini`. If any project config or autodetect path selects
   `gemini`, point the default provider at a working runtime (`claude` or `codex`) via
   `llm_provider.provider` in `sase.yml` so runs don't fail. The `gemini` runtime is dead for your
   (individual) account until migrated.

**Decision to make:**

2. Pick the path:
   - **(A) Migrate the `gemini` provider to `agy` (recommended).** Forward-looking, free-tier
     eligible, aligns with Google's direction. Cost: real engineering work (flag remap, prompt-via-`-p`
     instead of stdin, and possibly a parser rewrite).
   - **(B) Buy a Gemini Code Assist Standard/Enterprise license.** The existing `gemini` integration
     keeps working unchanged — zero code change. Downsides: ongoing cost, and you'd be investing in a
     product Google is steering away from (likely a dead end).
   - **(C) Drop Gemini as a runtime** if it isn't pulling its weight, and rely on Claude/Codex/others.

**Before writing any migration code — run the spike (this is the real "next action"):**

3. Install `agy` (`curl -fsSL https://antigravity.google/cli/install.sh | bash`), authenticate, and
   answer the one blocking question:
   ```
   agy -p "say hi" -m gemini-3-flash-preview --dangerously-skip-permissions
   ```
   then probe for any streaming/JSON output mode (`--output-format`, `--json`, `agy --help`).
   **The migration's whole shape depends on whether `agy` can emit a parseable streamed event
   stream.** If yes → adapt `_subprocess_gemini.py`. If no → decide between a text-only `-p` path
   (simpler, loses streaming/tool artifacts/usage) or treating Antigravity as a fundamentally
   different provider.

4. Read the official migration guide (`antigravity.google/docs/gcli-migration`) for the exact
   non-interactive flag set and the hook/skill/commit story, then open an SDD bead/plan for the
   provider migration with the spike's findings attached.

**Suggested sequencing:** (1) today → (3) spike → (2)/(4) decide & plan. Option (A) via the spike is
the recommended direction; (B) is a paid stopgap only if you need Gemini working *right now* and have
budget.

---

## 6. Open questions / risks

- **Output format (highest risk):** Does `agy` support streamed machine-readable output? Determines
  whether `_subprocess_gemini.py` is a light edit or a rewrite.
- **Prompt delivery:** `agy` takes the prompt via `-p`, not stdin — verify behavior with very long
  prompts / multi-line / special chars (arg-length limits vs. SASE's current stdin write).
- **Hook / skill / commit parity:** Does the `agy` harness honor SASE hooks, skills, and the commit
  workflow the way Gemini CLI did? (Required by the uniform-runtime rule.)
- **Model names:** Are SASE's pinned names (`gemini-3-flash-preview`, `gemini-3.1-pro`, etc.) still
  valid identifiers under `agy`?
- **Naming/identity:** Keep the provider id `gemini` (backed by `agy`) for config-compat, or introduce
  a new `antigravity`/`agy` provider? Affects entry points, registry colors, env vars
  (`SASE_GEMINI_PATH` vs `SASE_AGY_PATH`), and skill template context.
- **Doctor blind spot:** Add detection for the dead-tier signature so `sase doctor` stops reporting a
  broken runtime as healthy.

---

## Sources

- [An important update: Transitioning Gemini CLI to Antigravity CLI — Google Developers Blog](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [Bye-bye, Gemini CLI; Google nudges devs toward Antigravity — The Register](https://www.theregister.com/ai-ml/2026/05/20/bye-bye-gemini-cli-google-nudges-devs-toward-antigravity/5243605)
- [Google is Replacing Gemini CLI with Its New Antigravity Platform — OSTechNix](https://ostechnix.com/google-is-replacing-gemini-cli-with-google-antigravity/)
- [Gemini CLI Is Being Retired on June 18 — Meet Antigravity CLI (migration) — InventiveHQ](https://inventivehq.com/blog/gemini-cli-deprecated-antigravity-cli-migration)
- [Antigravity CLI: A Hands-On Guide to Google's Terminal Coding Agent — DEV Community](https://dev.to/arindam_1729/antigravity-cli-a-hands-on-guide-to-googles-terminal-coding-agent-5bc7)
- [Google Antigravity CLI: Orchestrating Parallel AI Agents — DataCamp](https://www.datacamp.com/tutorial/antigravity-cli)
- [google-antigravity/antigravity-cli — GitHub](https://github.com/google-antigravity/antigravity-cli)
- Local reproduction: `gemini` v0.35.0 → `IneligibleTierError: UNSUPPORTED_CLIENT` (free-tier), 2026-06-19.
- Codebase: `src/sase/llm_provider/gemini.py`, `src/sase/llm_provider/_subprocess_gemini.py`, `src/sase/doctor/checks_providers.py`.

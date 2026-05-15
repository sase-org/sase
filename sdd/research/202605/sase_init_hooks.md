# SASE Init Hooks Research

Date: 2026-05-15 (revised 2026-05-15)

## Goal

Add a `sase init-hooks` command that initializes SASE-managed hooks for every registered LLM provider without making
provider-specific assumptions in the command handler.

The command should reuse the CLI shape, chezmoi-aware deployment, and plugin-discovery model already established by
`sase init-skills`, while handling the structural differences between provider hook formats (JSON settings blocks,
standalone hook files, Go-templated chezmoi sources, OpenCode plugins, etc.).

## Canonical SASE Hook Events

The previous draft scoped the command to a single hook (`sase_commit_stop_hook`) plus the SASE-repo-local sibling hook.
That under-counts what SASE already manages today. Inspecting `~/.local/share/chezmoi/home/dot_{claude,codex,gemini,qwen}`
shows at least the following SASE-owned hook classes:

| Canonical SASE event | What it does                                                                | Where seen today                                                |
| -------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `commit-stop`        | Runs `sase_commit_stop_hook` after an agent response finishes.              | Claude `Stop`, Gemini `AfterAgent`, Qwen `Stop`, Codex `Stop`.  |
| `sibling-commit-stop`| Runs `tools/sase_sibling_commit_stop_hook` for SASE-development workspaces. | Codex `Stop` only today; should extend to other providers.      |
| `bead-prime`         | Runs `sase bead prime` (or `bd prime`) at session bootstrap and compaction. | Claude `SessionStart`, Claude `PreCompact`.                     |
| `deny-plan-mode`     | Denies `EnterPlanMode` / `ExitPlanMode` tool calls and surfaces `sase_plan`.| Claude `PreToolUse` (matchers `EnterPlanMode`, `ExitPlanMode`). |
| `deny-ask-user`      | Denies `AskUserQuestion` and surfaces `sase_questions`.                     | Claude `PreToolUse` (matcher `AskUserQuestion`).                |

Not every provider has a peer event for every SASE event:

- `PreCompact` and `SessionStart` are Claude concepts; Codex's `SessionStart` event was confirmed in current docs but
  the other providers either lack a session-start hook or expose it under different names.
- Claude's `PreToolUse` decision-by-stdout protocol does not have a direct analogue in Gemini/Qwen/Codex — those CLIs
  do not currently expose a pre-tool-call "permissionDecision: deny" extension point in their hook surface, so the
  `deny-*` events are effectively Claude-only until other providers add equivalents.

`init-hooks` should therefore treat each SASE event as **optional per provider**. A provider plugin that has no
mapping for a given canonical event simply returns nothing for it, and the command does not error. This stays
consistent with the "all runtimes are uniform" rule in `memory/short/gotchas.md`: the *interface* is uniform; the
event *coverage* differs because the upstream tools differ.

## Current Local State

`sase init-skills` is the closest existing command shape. It already supports provider filtering, dry runs, forced
overwrite, chezmoi-aware target paths, and optional commit/push/apply behavior. The hook command should reuse that CLI
shape rather than inventing a parallel UX.

Relevant files:

- `src/sase/main/parser_init.py`
- `src/sase/main/init_skills_handler.py`
- `src/sase/llm_provider/_hookspec.py`
- `src/sase/llm_provider/registry.py`
- `src/sase/scripts/sase_commit_stop_hook.py`
- `src/sase/llm_provider/_claude_hooks.py` (existing Claude JSON merge logic for transient tool-call hooks)
- `tools/sase_sibling_commit_stop_hook`

Existing generated or manually managed hook destinations:

| Provider | Global chezmoi source                                | Deployed to                          | Hook event(s) used today                       |
| -------- | ---------------------------------------------------- | ------------------------------------ | ---------------------------------------------- |
| Claude   | `dot_claude/settings.json`                           | `~/.claude/settings.json`            | `Stop`, `SessionStart`, `PreCompact`, `PreToolUse` |
| Gemini   | `dot_gemini/settings.json.tmpl` (Go-templated!)      | `~/.gemini/settings.json`            | `AfterAgent`                                   |
| Qwen     | `dot_qwen/settings.json`                             | `~/.qwen/settings.json`              | `Stop`                                         |
| Codex    | `dot_codex/hooks.json` (+ `config.toml` for trust)   | `~/.codex/hooks.json`                | `Stop`                                         |
| OpenCode | none today                                           | `~/.config/opencode/plugins/sase.ts` | plugin events (see below)                      |

SASE-repo-local hooks (deployed only when developing SASE itself, not via chezmoi):

| Provider | Path                              | Notes                                                       |
| -------- | --------------------------------- | ----------------------------------------------------------- |
| Claude   | `.claude/settings.json`           | Project-local override; tracked in this repo today.         |
| Gemini   | `.gemini/settings.json`           | Project-local override; tracked in this repo today.         |
| Qwen     | `.qwen/settings.json`             | Project-local override; tracked in this repo today.         |
| Codex    | (none committed)                  | Sibling hook is inlined into the global file via env-guard. |

Two important local constraints:

- Qwen Code sets both `QWEN_PROJECT_DIR` and `GEMINI_PROJECT_DIR`, so runtime detection in `sase_commit_stop_hook` must
  continue checking Qwen before Gemini.
- The live Qwen `settings.json` includes real API keys (`BAILIAN_TOKEN_PLAN_API_KEY`). The merge logic must round-trip
  every existing top-level key losslessly and must never print file content. Tests should assert that an unrelated
  secret-bearing key is preserved byte-for-byte after a merge.

## Provider Hook Formats

### Claude

Claude Code stores hooks in JSON settings files. User-global hooks live in `~/.claude/settings.json`; project hooks can
live in `.claude/settings.json` or `.claude/settings.local.json`. Hooks are nested as `event -> matcher group ->
handlers`. Command hooks receive JSON on stdin and can return decisions through JSON stdout
(`{"hookSpecificOutput": {...}}`) or event-specific exit-code behavior.

SASE already has robust Claude JSON merge logic for *transient* tool-call hooks in
`src/sase/llm_provider/_claude_hooks.py`. That code is a useful blueprint for the persistent init-hooks merger: load
existing JSON, preserve unrelated keys, write atomically, replace only SASE-managed entries.

The live `~/.local/share/chezmoi/home/dot_claude/settings.json` already contains a `statusLine` block and an
`enabledPlugins` map (the chezmoi-installed `claude-plugins-official` entries). `init-hooks` must not touch either —
the merge must operate strictly within `hooks.<event>`.

### Gemini

Gemini CLI hooks are configured in `.gemini/settings.json` or `~/.gemini/settings.json` under `hooks`. The completion
event is `AfterAgent`, not `Stop`. Timeouts are milliseconds.

**The chezmoi source is `dot_gemini/settings.json.tmpl` — a Go-templated file** containing constructs like
`{{ if eq .chezmoi.hostname "athena" }}oauth-personal{{ else }}gemini-api-key{{ end }}`. A naive JSON parser cannot
round-trip this file. Options for the command:

1. Edit the `.tmpl` source via line-level surgical replacement of the SASE-managed hook block while leaving every
   other line untouched. This is the safest option but requires a stable sentinel and is brittle if the user reformats.
2. Render the template once via `chezmoi cat` to produce concrete JSON, merge into JSON, and write the result back as
   raw JSON — losing the host-conditional logic. Not acceptable for shared/dotfile-managed settings.
3. Keep the SASE-managed hooks block in a *separate* `.tmpl` partial that the main settings template includes via
   `{{ template "sase-hooks" . }}`. `init-hooks` would only write that partial. This is the cleanest long-term split
   but requires migrating the existing chezmoi source.

Option 1 is the right starting point. The proposed sentinel scheme (below) makes that workable.

### Qwen

Qwen Code uses JSON settings files. User settings live in `~/.qwen/settings.json`; project settings live in
`.qwen/settings.json`. Qwen fires a Claude-style `Stop` event, not Gemini's `AfterAgent`, even though it also sets
Gemini environment variables. Timeouts are milliseconds.

Qwen's settings file regularly carries auth/model-provider data including API keys in plain text. See the secret
preservation constraint above.

### Codex

Confirmed against the current docs (https://developers.openai.com/codex/hooks):

- Canonical feature key is `features.hooks`; `codex_hooks` is a deprecated alias.
- Hooks are **enabled by default**; `init-hooks` should *not* write `[features] hooks = true` (no-op) and should not
  toggle it off.
- Hook sources discovered: `~/.codex/hooks.json`, `~/.codex/config.toml`, `<repo>/.codex/hooks.json`,
  `<repo>/.codex/config.toml`.
- Supported events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop`.
- Trust flow: `/hooks` slash command. From the docs: *"Use `/hooks` in the CLI to inspect hook sources, review new or
  changed hooks, trust hooks, or disable individual non-managed hooks."* SASE must surface this in the post-init
  output any time a Codex hook command string changes.

`init-hooks` should therefore prefer writing only `~/.codex/hooks.json` and never touch `[hooks.state]` in
`config.toml`. The current chezmoi-managed `dot_codex/hooks.json` already includes a user-specific
`zorg_sibling_commit_stop_hook` line — that is a leak of personal config into shared SASE artifacts and the new
command should not reproduce it. See "User-Owned Hook Extensions" below.

SASE's Codex provider launches Codex with a shadow `CODEX_HOME`: it copies `config.toml` and symlinks other home
entries such as `hooks.json`. Global hook initialization at `~/.codex/hooks.json` still flows through to SASE-managed
runs via that symlink, so no additional shadow-aware logic is required at init time.

### OpenCode

Confirmed against the current docs (https://opencode.ai/docs/plugins). OpenCode's extension surface is a TypeScript /
JavaScript plugin loaded from `.opencode/plugins/` or `~/.config/opencode/plugins/`.

Documented events relevant to a commit-stop equivalent:

- `session.idle` — fires when a session becomes inactive. Closest match to Claude `Stop` / Gemini `AfterAgent`.
- `session.updated`, `session.compacted`, `message.updated`, `message.part.updated` — finer-grained alternatives.
- `command.executed` — fires after slash-command execution.
- `tool.execute.before` / `tool.execute.after` — pre/post tool-call hooks; arguments are mutable in `before`.

There is **no documented event that explicitly signals "agent response finished"**, and the docs do not say whether
plugins run in `opencode run` one-shot mode or only in the interactive TUI. Before relying on `session.idle` for
commit-stop enforcement, prototype an `opencode run "echo hi"` invocation with a plugin that logs every event and
confirm the event actually fires in the non-interactive path. If it does not, OpenCode commit-stop enforcement must
happen on the SASE side (e.g., a wrapper that runs `sase_commit_stop_hook` after the `opencode run` subprocess exits)
rather than via a plugin hook.

Plugin file shape (per docs):

```ts
import type { Plugin } from "@opencode-ai/plugin"

export const SasePlugin: Plugin = async ({ project, client, $ }) => ({
  "session.idle": async ({ session }) => {
    await $`sase_commit_stop_hook`
  },
})
```

Caveats:

- Path resolution: prefer `PATH` lookup of `sase_commit_stop_hook`; fall back to project `.venv/bin/sase` only in a
  *project-scope* plugin.
- The `$` tagged template runs through Bun's `$` shell; stdin/stdout semantics differ from Claude/Gemini's hook
  protocol, so the script must work without consuming a JSON stdin payload.

## Recommended Architecture

Add provider-owned hook metadata to the LLM plugin contract instead of hard-coding provider names in the CLI handler.
This keeps the command aligned with the existing "all runtimes are uniform" rule and lets external provider plugins
participate later.

Suggested additions to `LLMHookSpec`:

```python
@hookspec(firstresult=True)
def llm_hook_targets(
    scope: Literal["global", "project"],
    events: frozenset[SaseHookEvent],
) -> list[LLMHookTarget]: ...
```

```python
class SaseHookEvent(str, Enum):
    COMMIT_STOP = "commit-stop"
    SIBLING_COMMIT_STOP = "sibling-commit-stop"
    BEAD_PRIME = "bead-prime"
    DENY_PLAN_MODE = "deny-plan-mode"
    DENY_ASK_USER = "deny-ask-user"

@dataclass(frozen=True)
class LLMHookTarget:
    provider: str
    scope: Literal["global", "project"]
    event: SaseHookEvent
    relative_path: str               # e.g. ".claude/settings.json"
    chezmoi_relative_path: str | None  # e.g. "dot_gemini/settings.json.tmpl"
    format: Literal["json-settings", "codex-hooks-json", "opencode-plugin", "tmpl-go"]
    payload: Mapping[str, Any] | str  # event-specific structured data, or file content for plugin formats
    managed_id: str                  # stable SASE id used as the merge sentinel
    description: str
```

Two-layer responsibility split:

1. **SASE-side**: owns the canonical event list (`SaseHookEvent`) and the *behavior* each event encodes (which
   command to run, what arguments, what messaging on deny). Centralizing this means changing the deny message for
   `EnterPlanMode` is a one-line change, not five.
2. **Provider plugin**: owns the *format-specific* mapping — which native event name, which file, which schema,
   which timeout unit (seconds vs milliseconds), which sentinel placement. Plugins return an empty list for events
   they cannot express.

The new command should:

1. Discover providers through `iter_plugins()`.
2. Filter providers by `--provider` and events by `--event` (default: all).
3. Ask each provider for hook targets for the requested scope + events.
4. Resolve target paths using the same home/chezmoi pattern as `init-skills`.
5. Merge structured files using the sentinel-keyed strategy below.
6. Print changed/skipped paths, actionable warnings (e.g., "run `/hooks` in Codex"), and a per-event coverage summary.
7. Reuse the chezmoi deploy sequence factored out of `init-skills`.

## CLI Shape

```
sase init-hooks
  -p, --provider {claude,gemini,codex,opencode,qwen}   (matches init-skills)
  --scope {global,project,all}                          default: global
  --event {commit-stop,sibling-commit-stop,bead-prime,deny-plan-mode,deny-ask-user}   repeatable; default: all
  -n, --dry-run
  -f, --force
  --check                Exit non-zero if deployed hooks drift from generated output.
  --uninstall            Remove SASE-managed entries (matched by sentinel) without touching unrelated keys.
  --no-commit            (chezmoi deploy parity with init-skills)
  --no-push
  --no-apply
```

`--scope project` should only write repo-local SASE-development hooks when the current working directory contains the
expected sibling-hook executable. For non-SASE projects, the project scope currently has nothing meaningful to deploy
and should print a clear no-op message rather than scribbling empty hook files.

`--check` and `--uninstall` are the two surface gaps the original draft did not cover; both fall out naturally from
the sentinel-based identification model and are cheap to implement once the merger exists.

## Identification: How "SASE-Managed" Is Encoded

For formats that do not allow comments (JSON), the merger needs an unambiguous way to recognize which entries SASE
owns. Two complementary signals:

1. **Command-string match**: an entry whose `command` is literally `sase_commit_stop_hook` (or starts with
   `sase_commit_stop_hook ` after argument stripping) is treated as SASE-managed. This handles the legacy entries
   already in the wild and avoids the chicken-and-egg problem of "first run finds no sentinel".
2. **Sentinel key**: newly written entries include an extra `_sase` object: `{"id": "<managed_id>", "v": 1,
   "event": "commit-stop"}`. Claude, Gemini, Qwen, and Codex all tolerate extra unknown keys in `hooks[*].hooks[*]`
   in current releases; the merger should add this on write and prefer matching by sentinel on subsequent runs.

Spike: write a tiny test harness that boots each provider against a settings file containing the sentinel and
verifies it does not error or strip the key. If any provider does strip it, fall back to command-string-only matching
for that provider.

## Merge Rules

For JSON settings files (Claude, Gemini-as-rendered, Qwen):

- Parse existing JSON; if malformed, skip unless `--force` and emit a clear error pointing at the file.
- Preserve every unrelated top-level key byte-for-byte, including secret-bearing keys (`env`, `modelProviders`,
  `auth`).
- Ensure `hooks.<event>` is a list; create the list if missing.
- For each SASE event being seeded, locate existing SASE-owned entries via sentinel-then-command-string and either
  replace them in place or append.
- De-dupe by `(event, command, sentinel.id)`.
- Preserve file mode (Qwen settings may be 0600; do not widen).
- Write atomically (`tempfile` in same directory + `os.replace`) under an `fcntl.flock` on the target — concurrent
  agents may otherwise race on writes.
- Trailing newline + 2-space indent matches existing chezmoi-formatted JSON. Run `prettier` if available, like
  `init-skills` does.

For Gemini chezmoi `.tmpl`:

- Do not parse as JSON. Locate the SASE-managed block by a paired sentinel comment:
  `{{/* sase-hooks:start id=commit-stop@v1 */}} ... {{/* sase-hooks:end id=commit-stop@v1 */}}` and replace
  in-place. Leave the rest of the template untouched.
- On first run, insert the block after the existing `"hooks":` key if present; otherwise append a top-level `hooks`
  object using template-safe whitespace.
- Validate with `chezmoi execute-template` after writing if available.

For Codex `hooks.json`:

- Prefer writing only `hooks.json`.
- Never write `[hooks.state]`.
- Never blindly rewrite `config.toml`. If a future option toggles `[features] hooks = false -> true`, use a
  TOML-preserving writer (e.g., `tomlkit`) rather than reserializing — `config.toml` includes user-specific keys.
- After any change, print: `Run \`codex\` and \`/hooks\` to review and trust the new commands.`

For OpenCode:

- Generate `~/.config/opencode/plugins/sase.ts` (or the chezmoi-template equivalent). Single file, sentinel-marked
  header comment so the user can spot it.
- Do not embed user-specific paths. Resolve `sase_commit_stop_hook` from `PATH`.
- For a *project-scope* plugin in the SASE repo, allow falling back to `.venv/bin/sase`.

## User-Owned Hook Extensions

The chezmoi-committed `dot_codex/hooks.json` currently includes a `zorg_sibling_commit_stop_hook` entry — that hook
points at a personal sibling repo and should never have been committed alongside SASE-shared config. The new command
must avoid recreating this leak while still letting individual users add their own sibling hooks.

Proposed pattern:

- SASE-managed entries are written via the sentinel scheme above.
- The merger leaves *all* non-SASE-managed entries untouched. Users can hand-add sibling-repo hooks and they will
  persist across `init-hooks` runs.
- Document the recommended pattern in AGENTS.md: name personal hook commands with a `*_sibling_commit_stop_hook`
  convention and let the user add them via plain text edits.

Optionally, add a `~/.config/sase/user-hooks.yml` for the user to declare their own canonical hooks that
`init-hooks` will template into provider format. Out of scope for v1.

## Concurrency and Atomicity

Multiple SASE agents can run in parallel and a poorly timed `init-hooks` could collide with a Claude `temporary_hook`
update. Two requirements:

- Wrap reads + writes of any settings file in `fcntl.flock` (LOCK_EX) on the file itself, with a small retry loop.
  `src/sase/llm_provider/_claude_hooks.py` already does this for the transient flow; the new merger should reuse
  that helper.
- Write through a temp file in the same directory + `os.replace`, never in-place truncate-then-write.

## Verification: `--check` Mode

`--check` runs the full merger in memory, compares the result to what is on disk, and exits non-zero on drift.
Useful for:

- CI assertion that `init-hooks` was re-run after a SASE event surface change.
- Pre-flight diagnostic when an agent reports a hook is missing (`sase init-hooks --check --provider claude`).

Output should be a unified diff of the *managed* entries only, never the whole file (to avoid printing secrets).

## Main Risks

- Codex hook trust: changed hooks require `/hooks` review; SASE must announce this loudly.
- Unit mismatch: Claude/Codex timeouts are seconds; Gemini/Qwen timeouts are milliseconds. The per-provider plugin
  owns the unit conversion.
- Qwen/Gemini runtime ambiguity: Qwen must stay first in runtime detection because it exports Gemini env vars too.
- Secret-bearing configs: do not log or echo file content; verify in tests that round-tripping preserves unrelated
  keys byte-for-byte.
- Chezmoi `.tmpl` round-trip for Gemini: JSON parsers cannot edit Go-templated files. Use sentinel-bracketed text
  replacement instead.
- OpenCode semantics: `session.idle` is documented but not confirmed to fire in `opencode run` one-shot mode. Verify
  before claiming feature parity with Claude/Gemini/Qwen.
- Sentinel acceptance: each CLI must accept the extra `_sase` key on hook objects without erroring or stripping it.
  Verify in a quick spike before relying on it.
- User-owned entries: the merger must *not* delete unfamiliar entries. Drift-detection mode (`--check`) should ignore
  non-SASE entries entirely.

## Suggested Implementation Sequence

1. Extract `init-skills` chezmoi deploy helpers into a small shared module
   (`src/sase/main/_init_chezmoi_deploy.py`).
2. Add the `SaseHookEvent` enum, `LLMHookTarget` dataclass, and `llm_hook_targets` hookspec.
3. Implement the JSON merger with sentinel-based identification and `fcntl.flock` locking. Cover Claude, Gemini
   (rendered JSON), Qwen formats. Tests must assert: (a) byte-preservation of unrelated keys, (b) idempotency under
   repeated runs, (c) safe behavior on malformed JSON, (d) recognition of legacy entries by command-string.
4. Implement the Codex `hooks.json` writer; emit the `/hooks` trust message on any change.
5. Implement the Gemini chezmoi `.tmpl` block-replacement path with sentinel comments. Add a `chezmoi
   execute-template` validation step.
6. Add provider hook-target hookimpls for Claude, Gemini, Qwen, Codex covering the events each supports.
7. Validate OpenCode `session.idle` in `opencode run` mode. If it fires, ship the plugin; otherwise, ship a
   subprocess-side commit-stop fallback in `_subprocess_opencode.py` and document the divergence.
8. Add `init-hooks` parser and handler with `--dry-run`, `--check`, `--uninstall`, `--force`, `--scope`, `--event`.
9. Add end-to-end tests for provider filtering, scope handling, malformed JSON recovery, sentinel identification,
   uninstall completeness, and chezmoi deploy parity with `init-skills`.
10. Update AGENTS.md / build_and_run.md with the new command.

## Open Questions

- Should `--scope project` in a non-SASE repo do anything, or always no-op? (Recommend no-op + warning for v1.)
- Should `init-hooks` also seed the Claude `statusLine` block and `env` block, or only `hooks.<event>`? (Recommend
  `hooks` only for v1; statusLine and env are presentation/runtime config, not hooks.)
- Should there be a `just init-hooks` justfile target mirroring `just install`? (Probably yes for discoverability.)
- Should `LLMHookTarget.payload` be a SASE-side canonical structure that the provider plugin transforms to its
  format, or should the plugin emit the final format directly? (Recommend canonical structure to keep behavior
  changes in one place; format-specific transformation lives in the plugin.)
- Is `_sase` as the sentinel key safe across all four JSON-format providers, or should it be a more obscure name
  (`x-sase`, `__sase_managed__`)? Decide after the acceptance spike.
- Should hook commands launched via `init-hooks` resolve `sase_commit_stop_hook` from `PATH` only, or also fall back
  to `$CLAUDE_PROJECT_DIR/.venv/bin/sase` style logic like the existing `bead prime` hook does? (Recommend
  PATH-first, project-venv-fallback as a documented pattern in the canonical event definition.)

## Sources

- Claude hooks reference: https://code.claude.com/docs/en/hooks
- Gemini hooks reference: https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/hooks/reference.md
- Gemini hook examples: https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/hooks/writing-hooks.md
- Qwen hooks reference: https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/
- Qwen settings reference: https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/
- Codex hooks reference: https://developers.openai.com/codex/hooks (verified: `features.hooks` canonical;
  enabled-by-default; `/hooks` slash command for trust review; supported events `SessionStart`,
  `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop`)
- OpenCode plugin reference: https://opencode.ai/docs/plugins (verified: `session.idle`, `session.updated`,
  `tool.execute.before/after`, `command.executed`; no documented agent-response-finished event; non-interactive
  `opencode run` plugin behavior not specified)
- OpenCode config reference: https://opencode.ai/docs/config
- Existing local artifacts inspected: `~/.local/share/chezmoi/home/dot_{claude,codex,gemini,qwen}/`,
  `tools/sase_sibling_commit_stop_hook`, `src/sase/llm_provider/_claude_hooks.py`,
  `src/sase/main/init_skills_handler.py`.

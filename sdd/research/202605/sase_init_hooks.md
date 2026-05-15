# SASE Init Hooks Research

Date: 2026-05-15

## Goal

Add a `sase init-hooks` command that initializes SASE-managed hooks for every registered LLM provider without making
provider-specific assumptions in the command handler.

The command should cover the two hook classes SASE already relies on:

- Global SASE hooks that should run regardless of the project directory, especially `sase_commit_stop_hook`.
- SASE-repo-local hooks that only make sense when developing SASE itself, especially `tools/sase_sibling_commit_stop_hook`.

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
- `tools/sase_sibling_commit_stop_hook`

Existing generated or manually managed hook destinations:

| Provider | Global location | SASE repo-local location | Stop-like event |
| --- | --- | --- | --- |
| Claude | `~/.claude/settings.json` | `.claude/settings.json` | `Stop` |
| Gemini | `~/.gemini/settings.json` | `.gemini/settings.json` | `AfterAgent` |
| Qwen | `~/.qwen/settings.json` | `.qwen/settings.json` | `Stop` |
| Codex | `~/.codex/hooks.json` plus `~/.codex/config.toml` | none today | `Stop` |
| OpenCode | none found today | none found today | plugin event, likely `session.idle` for completion-like behavior |

Two important local constraints:

- Qwen Code sets both `QWEN_PROJECT_DIR` and `GEMINI_PROJECT_DIR`, so runtime detection in `sase_commit_stop_hook` must
  continue checking Qwen before Gemini.
- Some provider settings files contain auth/model-provider data. `init-hooks` must merge only hook entries and preserve
  unrelated top-level keys without echoing secrets in output.

## Provider Hook Formats

### Claude

Claude Code stores hooks in JSON settings files. User-global hooks live in `~/.claude/settings.json`; project hooks can
live in `.claude/settings.json` or `.claude/settings.local.json`. Hooks are nested as event -> matcher group -> handlers.
Command hooks receive JSON on stdin and can return decisions through JSON stdout or event-specific exit-code behavior.

SASE already has robust Claude JSON merge logic for temporary tool-call hooks in `src/sase/llm_provider/_claude_hooks.py`.
That code is a good model for an init-hooks JSON merge helper: load existing JSON, preserve user entries, write atomically,
and remove or replace only SASE-managed entries.

### Gemini

Gemini CLI hooks are configured in `.gemini/settings.json` or `~/.gemini/settings.json` under `hooks`. Gemini uses
Gemini-family event names; the completion validation hook is `AfterAgent`, not `Stop`. Timeouts are milliseconds.

The current SASE configs already use:

```json
{
  "hooks": {
    "AfterAgent": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "sase_commit_stop_hook",
            "timeout": 300000
          }
        ]
      }
    ]
  }
}
```

For repo-local SASE development, the command currently points to
`"$GEMINI_PROJECT_DIR"/tools/sase_sibling_commit_stop_hook`.

### Qwen

Qwen Code uses JSON settings files. User settings live in `~/.qwen/settings.json`, and project settings live in
`.qwen/settings.json`. Qwen fires a Claude-style `Stop` event, not Gemini's `AfterAgent`, even though it also sets
Gemini environment variables. Timeouts are milliseconds.

The current global SASE hook is `sase_commit_stop_hook` on `Stop`; the repo-local hook uses
`"$QWEN_PROJECT_DIR"/tools/sase_sibling_commit_stop_hook`.

### Codex

Codex discovers hooks from `hooks.json` files next to active config layers or inline `[hooks]` tables in `config.toml`.
The current docs say `features.hooks` is the canonical feature key, with `codex_hooks` still accepted as a deprecated
alias. Current hooks are enabled by default, so the safest generated surface is `~/.codex/hooks.json`; avoid modifying
`config.toml` unless the command has an explicit compatibility mode.

Current SASE global Codex hooks:

- `sase_commit_stop_hook`
- a SASE sibling hook guarded by an executable check under `${CODEX_PROJECT_DIR:-$PWD}/tools/...`
- a similar `zorg` sibling hook, which looks user-specific and should not be hard-coded into SASE source

Codex has a hook review/trust mechanism recorded under `[hooks.state]` in `config.toml`. `init-hooks` should not attempt
to synthesize or mutate trusted hashes. It should write `hooks.json` and report that the user may need to review changed
hooks with Codex's `/hooks` UI.

SASE's Codex provider launches Codex with a shadow `CODEX_HOME`: it copies `config.toml` and symlinks other home entries
such as `hooks.json`, so global hook initialization still affects SASE-managed Codex runs.

### OpenCode

OpenCode does not use the same Claude/Gemini JSON hook block. Its official extension mechanism is JavaScript/TypeScript
plugins loaded from `.opencode/plugins/` or `~/.config/opencode/plugins/`. Plugins subscribe to events such as
`tool.execute.before`, `tool.execute.after`, `shell.env`, and session events including `session.idle`.

For parity with the other providers, model OpenCode as a provider with hook initialization support, but generate a plugin
file rather than a JSON settings hook. A first SASE hook plugin can call `sase_commit_stop_hook` when the session becomes
idle. Before implementation, verify whether `session.idle` can block or feed back into a non-interactive `opencode run`
the way SASE's commit-stop workflow expects. If it cannot, the plugin can still provide telemetry/notification behavior,
but commit-stop enforcement may need a provider-side post-run fallback.

## Recommended Architecture

Add provider-owned hook metadata to the LLM plugin contract instead of hard-coding provider names in the CLI handler.
This keeps the command aligned with the existing "all runtimes are uniform" rule and lets external provider plugins
participate later.

Suggested additions:

- `LLMHookSpec.llm_hook_targets(scope: Literal["global", "project"]) -> list[LLMHookTarget]`
- `LLMHookTarget` dataclass with:
  - `relative_path`: provider config path under provider home or project root
  - `chezmoi_relative_path`: optional override for template paths such as `dot_gemini/settings.json.tmpl`
  - `format`: `json-settings`, `codex-hooks-json`, `toml-feature`, or `opencode-plugin`
  - `provider`: provider name
  - `scope`: `global` or `project`
  - `description`
  - `payload`: generated structured data or text
  - `managed_id`: stable SASE id for replacement/deduplication

The new command should:

1. Discover providers through `iter_plugins()`.
2. Ask each provider for hook targets for the requested scope.
3. Resolve target paths using the same home/chezmoi pattern as `init-skills`.
4. Merge structured files instead of blindly overwriting them.
5. Print changed/skipped paths and actionable warnings.
6. Reuse or extract the existing chezmoi deploy sequence from `init-skills`.

## CLI Shape

Recommended first-pass options:

- `sase init-hooks`
- `--provider {claude,gemini,codex,opencode,qwen}` matching `init-skills`
- `--scope {global,project,all}` with `global` as the safer default
- `--dry-run`
- `--force`
- `--no-commit`, `--no-push`, `--no-apply` with the same meaning as `init-skills`
- `--compat-codex-feature-flag` only if we decide to edit Codex `config.toml`

`project` scope should only write repo-local sibling hooks when the expected sibling hook executable exists in the
current project. Otherwise it should skip with a clear warning rather than writing broken project config.

## Merge Rules

For JSON settings files:

- Parse existing JSON as an object; if malformed, skip unless `--force`.
- Preserve every unrelated key.
- Ensure `hooks.<event>` is a list.
- Replace an existing SASE-managed entry by stable marker when possible; otherwise de-dupe by exact generated command.
- Write with deterministic indentation and a trailing newline.
- Use atomic writes.

For Codex:

- Prefer writing `hooks.json` only.
- Do not write `[hooks.state]`.
- Do not blindly rewrite `config.toml`; the current docs no longer require enabling hooks, and preserving trust state is
  more important than forcing a feature flag.
- If compatibility mode is implemented, only set `[features].hooks = true` with a TOML-preserving writer or a tightly
  scoped edit. Avoid reserializing the whole file without a TOML writer dependency.

For OpenCode:

- Generate a small plugin under `~/.config/opencode/plugins/sase-hooks.js` or the chezmoi equivalent.
- Avoid embedding user-specific paths.
- Prefer resolving `sase_commit_stop_hook` from `PATH`; optionally fall back to a project `.venv/bin/sase` only in a
  project-local plugin.

## Main Risks

- Codex hook trust: changed hooks may require manual review in `/hooks`; SASE should not bypass that state.
- Unit mismatch: Claude/Codex timeouts are seconds; Gemini/Qwen timeouts are milliseconds.
- Qwen/Gemini runtime ambiguity: Qwen must stay first in runtime detection because it exports Gemini env vars too.
- Secret-bearing configs: generated output must merge into existing files without printing or replacing auth/model
  provider config.
- OpenCode semantics: plugins clearly provide events, but the commit-stop hook may need more validation before claiming
  full blocking behavior.
- Chezmoi templates: Gemini currently uses `settings.json.tmpl`, so target resolution needs a provider override rather
  than assuming every settings file is a plain JSON filename.

## Suggested Implementation Sequence

1. Extract `init-skills` chezmoi deploy helpers into a small shared module.
2. Add `init-hooks` parser and handler with dry-run support.
3. Add provider hook metadata hookimpls for Claude, Gemini, Qwen, and Codex.
4. Implement JSON merge and atomic write helpers with focused tests.
5. Implement Codex `hooks.json` generation, with a warning about `/hooks` review.
6. Add OpenCode plugin generation after validating `session.idle` behavior in `opencode run`.
7. Add tests for provider filtering, scopes, chezmoi target paths, malformed JSON, idempotency, and preservation of
   unrelated config keys.

## Sources

- Claude hooks reference: https://code.claude.com/docs/en/hooks
- Gemini hooks reference: https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/hooks/reference.md
- Gemini hook examples: https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/hooks/writing-hooks.md
- Qwen hooks reference: https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/
- Qwen settings reference: https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/
- Codex hooks reference: https://developers.openai.com/codex/hooks
- OpenCode config reference: https://opencode.ai/docs/config
- OpenCode plugin reference: https://opencode.ai/docs/plugins

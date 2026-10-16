---
title: "Feature flag configuration"
description: "Configuration and persisted state for SASE feature flags."
---

# Feature flag configuration

Configuration and persisted state for SASE feature flags.

<a id="featureflags"></a>

## feature_flags

`feature_flags` is the portable user and project override surface for code-owned SASE
feature flags. Registry defaults live in `src/sase/feature_flags/registry.py`; the
config block only overrides registered keys. It remains valid and lower-precedence than
a saved machine preference. The Config **Flags** pane and `sase flag enable` /
`sase flag disable` never edit this block, overlays, project-local `sase.yml`, or
chezmoi source.

```yaml
feature_flags:
  demo_key: true
```

The generated JSON Schema exposes one boolean property per registered flag with its
description and default. Unknown keys are tolerated by the schema so downgraded installs
can still read a config written by a newer SASE, but the resolver warns and ignores
unknown keys at runtime.

`beta` flags default off and gate work that is still landing; `sunset` flags default on
and keep a fallback path reachable until the flag is removed. The schema marks sunset
flags deprecated. One sunset flag is currently registered:
`artifacts_agent_pane_retired` (default on) hides the Artifacts ▸ Agent sub-tab and
moves agent history to the Agents tab Archive (`,a`). To opt out and restore the pane,
run `sase flag disable artifacts_agent_pane_retired` or set
`feature_flags: {artifacts_agent_pane_retired: false}` in configuration. Apart from that
flag, the typed sudo request workflow (`sase sudo`) and its review modal are always
available, only `agent_meta.autonomy` carries `%auto` state, and a hard provider disable
relaunches stranded agents through `sase agent drain` (see `llm_provider.usage_limit`
and Launch Control's automatic provider drain in `ace.md`).

`agent_decks` and `agent_tabs` are no longer registered. The Agents tab always shows
[data decks and cards](../../ace.md#agent-data-decks-and-cards) and
[agent tabs](../../ace.md#agent-tabs). A saved preference for a flag that is no longer
registered is removed the next time an installing process reconciles
`feature_flags.json`.

The retired family keyword on `%id` is always accepted as `session=`, the `family` and
`kind` agent-query values are always accepted as `session:` and `kind:session`, and the
`--next-fork` family value, a gate `"fork": "family"`, and `SASE_AGENT_FAMILY_ATTACH`
always normalize to their session replacements. The retired shell spellings are always
accepted as well: `sase gate create --shell`, `--shell-status`, `--shell-stop-status`,
and the `--next-fork` shell value; a gate spec's `"shell"` block, the `"fork"` key set
to `"shell"`, and `"continuation_mode": "gate_shell"`; `--shell` on `sase proc list` or
`sase proc run` (replaced by `--name`); and the retired `gate.shell`
`.reclaim_grace_seconds` key. Supplying both names for the same option or block is an
error. Write the session and turn spellings in new prompts and config, and use `--name`
for proc commands.

The retired macro spellings in
[the macro rename section](../upgrading/macros.md#retired-macro-spellings) are always
accepted. Supplying a retired spelling in a new command, config key, frontmatter key,
environment variable, or `sase path` target resolves to its replacement. The retired
entry-point group is still loaded, a plugin's packaged copy of the retired definition
directory is still read, and those retired directories stay visible to expansion,
workflow loading, completion, catalogs, and save choices. Config keys, frontmatter keys,
and the plugin-disable environment variable are an error when both the retired name and
the macro name are present. The LSP command environment variable is the exception: a
non-empty macro value wins and the retired value is ignored. See that section for which
names those are. The region alias there stays accepted. State files and agent artifact
filenames already written under the old names stay readable, and new writes use only the
macro spelling. A default `sase doctor` run includes the config check for those retired
authored surfaces. It reports non-empty retired definition directories and does not
report those state files, agent artifact filenames, or that region alias.

When an owner-manifest hood entry still carries an explicit `files` list, readers accept
a missing list, and a present list may be the current canonical set or the legacy set,
which is that current set with every `sessions/` path removed and the legacy redirect
stubs retained. See [Strict v2 layout](../../agents_sidecar.md#strict-v2-layout).

Run `sase flag list` for the live registry with effective and saved state.

`%if::` script-admission and `%proc` are always available: parser, completion, and
launch-plan contract included. Static `%if(should_run=true|false)` segment omission
works before typed launch planning. User-initiated sase's TUI and `sase run` submissions
execute typed directives through durable typed admission without a LaunchApproval gate.
The frozen plan keeps the complete `%id` and `%clan` identity binding, and keyed
`{@<id>}` markers resolve once at batch creation. Agent-initiated launches still freeze
the typed plan for LaunchApproval; after approval, the same admission coordinator
resolves waits, evaluates `%if::` predicates, and dispatches eligible units — agent
units through the established agent launch path, and `%proc` units through native
stand-alone named-proc dispatch; see
[Typed launch units](../macros/directive-syntax.md#typed-launch-units).

### Saved machine preferences

Persistent enable/disable choices live in a SASE-owned machine-state file
`$SASE_HOME/feature_flags.json` (normally `~/.sase/feature_flags.json`), not in
configuration. The file is a bounded JSON object of exact booleans keyed by registered
flag names; equal-to-default values are still stored because enable and disable are
durable user choices. Inspect the path with `sase flag show <key>` or the Flags pane
detail card (`STATE`).

```json
{
  "version": 1,
  "flags": {
    "demo_key": true
  }
}
```

Missing state is an empty snapshot (every flag uses its registry/config default). A
malformed, oversized, or unsupported whole file is not silently deleted or overwritten:
reads return no preferences plus a diagnostic, mutations fail with the path and a
recovery-oriented message, and registered flags still resolve from lower layers.

Valid unknown keys in the machine-state file are tolerated by registry-neutral reads and
writes, but installing process-wide feature flags for sase's TUI, AXE, or an agent
runner reconciles that file against the running SASE registry and removes saved entries
that are no longer registered. sase's TUI defers the disk transaction until the
initially visible surface is ready, then shows one cleanup toast; AXE and agent runners
report the same cleanup on stderr. Clean starts do not rewrite the file or emit cleanup
prose. If another process already removed the stale keys, sase's TUI reports that the
previously unregistered saved keys are already absent. If cleanup fails or the file
becomes unusable, SASE preserves the file, keeps the diagnostic, and retries on the next
startup.

This means downgrading or misspelling a saved flag no longer preserves that saved key
past the next installing process. A later upgrade falls back to registry/config defaults
until the choice is saved again. Portable YAML `feature_flags` entries keep the older
tolerance: unknown config keys are diagnosed and ignored, not rewritten.

### Resolution order

Effective value is resolved in this order, later sources winning:

```text
registry default
  < user config
  < overlay config
  < saved machine preference (SAVED)
  < explicit in-process/test override
  < SASE_FEATURE_FLAGS transport / legacy env
  < root CLI -f/--enable-feature or -F/--disable-feature
```

Plugin config layers never flip first-party flag defaults. A local-config entry for any
feature flag is ignored with a `scope_violation` warning: a feature flag cannot be set
from the `local` config layer, because sase's TUI disables project-local config and
flags must resolve consistently across frontends.

The Flags pane and `sase flag list` / `show` report **effective** state and **saved**
state separately. Provenance `SAVED` means the machine-state file won. If environment or
root CLI overrides still shadow the saved choice, the UI shows a “forced for this
process” warning rather than pretending the toggle already controls this process. Saving
still restarts sase's TUI and the service host; the saved value takes effect once that
higher source is removed.

Root-level `-f/--enable-feature` and `-F/--disable-feature` force a registered flag on
or off for one `sase` invocation. They must appear before the subcommand
(`sase -f demo_key run "..."`). They outrank every config layer, a saved machine
preference, and an inherited `SASE_FEATURE_FLAGS` value, and they merge into
`SASE_FEATURE_FLAGS` so launched agents and other child processes inherit the same
overrides.

`SASE_FEATURE_FLAGS` is a strict JSON object of booleans, for example
`{"demo_key":false}`. Malformed JSON, a non-object payload, or a non-boolean value is a
startup error for that process. SASE-launched children inherit a resolved snapshot
through the same variable, so `sase flag list` marks env provenance prominently. CLI
overrides are marked the same way (`CLI:--enable-feature` / `CLI:--disable-feature`).
After a successful save, SASE merges the chosen key into `SASE_FEATURE_FLAGS` so an
sase's TUI `execv` restart does not inherit the old pinned snapshot above the new saved
value.

### Enable, disable, and restart

```text
sase flag enable <flag>
sase flag disable <flag>
```

Both commands persist the choice in the machine-state file and, on success, restart the
`scheduler` service proc when it is already running. A stopped scheduler is left
stopped. They never start a proc the user had stopped, and they never signal a sase's
TUI session in another terminal — restart any separately running sase's TUI yourself.
Repeating an already-saved enable or disable is idempotent for the store but still
retries that scheduler restart. A restart failure does not roll back the saved
preference: rich and JSON output distinguish `mutation` from `restart` so a partial
success is safe to retry. Unknown flags are usage errors (exit `2`); store or restart
failures use exit `1`. `--json` emits one versioned document with separate `mutation`
and `restart` objects.

From Config > Flags, a confirmed toggle uses the same mutation path, then waits for
TUI-local tasks and installation changes and performs one controlled sase's TUI and
service host restart. Independent commands keep running.

Create temporary flags with `sase flag new <key>` rather than editing the registry by
hand. The command creates a task bead of type `flag`, prints the registry entry, and
gives the both-states test checklist. Kinds are `beta` (default off) and `sunset`
(default on); the registry default is derived from the kind. See
[Beads](../work-units/bead-lifecycles.md#flag-bead-lifecycle) for the removal lifecycle.

Source: `src/sase/feature_flags/registry.py`, `src/sase/feature_flags/schema.py`,
`src/sase/feature_flags/snapshot.py`, `src/sase/feature_flags/state.py`

## Related

- [Integrations and telemetry configuration](integrations.md) — generated feature flag
  keys.
- [Feature flag reference](../../ace.md#config-flags-pane) — flag controls.

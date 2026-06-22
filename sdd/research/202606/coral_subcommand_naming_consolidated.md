# Coral Subcommand Naming Research - Consolidated

Date: 2026-06-22

This consolidates the two prior research notes:

- `sdd/research/202606/coral_subcommand_naming_research.md`
- `sdd/research/202606/coral_subcommand_naming_research_20260622.md`

## Question

If `sase` becomes `coral`, what should replace the `ace` and `axe` subcommands, and what should replace Axe's
`lumberjack` and `chop` vocabulary?

The bar is not "find clever coral words." The names need to remain close to what the commands actually do, be easy to
type in daily CLI use, and avoid forcing users to learn a private metaphor before operating the system.

## Verified Current Meanings

Local docs and parser definitions confirm the surfaces that need renaming:

| Current term | Role to preserve |
| --- | --- |
| `sase ace` | The interactive TUI / control surface for ChangeSpecs, agents, automation, notifications, review, and prompt launch. ACE expands to "Agentic ChangeSpec Explorer." |
| `sase axe` | The schedule-driven background automation daemon. It starts/stops an orchestrator, runs periodic lifecycle work, and is auto-started by ACE unless disabled. |
| `lumberjack` | A named scheduler loop with its own interval, state, metrics, logs, and configured set of jobs. Defaults include `hooks`, `waits`, `checks`, `comments`, and `housekeeping`. |
| `chop` | One runnable job unit inside a lumberjack. It may be a script or agent launch, has history/logs/status, and can run on schedule or manually. |

The important constraint: `lumberjack` is more than a thread name, and `chop` is more than an implementation detail.
Both are operator-facing CLI, config, state-path, log, and TUI concepts.

## Conflict Resolution

The two prior agents agreed that `ace` should become **`reef`**. They disagreed on the `axe` family:

- **`reel/angler/cast`** best preserves the current `ace`/`axe` twin aesthetic and the `tool -> worker -> action`
  metaphor.
- **`tide/current/job`** best matches the actual behavior: scheduled, recurring background movement made of named flows
  and explicit runnable jobs.

Final choice: prefer **`tide/current/job`**. The user asked for names that are related but easy to understand and "not
too distant from what the command actually does." `reel/angler/cast` is clever and coherent, but it shifts the system
from coral/reef vocabulary into fishing vocabulary, and `reel` does not clearly say "daemon" or "scheduler" without an
extra explanation.

## Primary Recommendation

Use:

```text
sase ace              -> coral reef
sase axe              -> coral tide
sase axe lumberjack   -> coral tide current
sase axe chop         -> coral tide job
```

Example command tree:

```bash
coral reef [QUERY] [options]

coral tide start
coral tide stop
coral tide maintenance enter --reason "..."
coral tide maintenance status
coral tide maintenance exit

coral tide current list
coral tide current status
coral tide current run hooks

coral tide job list
coral tide job run hook_checks
coral tide job run hook_checks --current hooks
```

Recommended config vocabulary:

```yaml
tide:
  max_hook_runners: 3
  max_agent_runners: 3
  zombie_timeout_seconds: 7200
  job_script_dirs: []
  currents:
    hooks:
      interval: 5
      job_timeout: "90s"
      jobs:
        - name: hook_checks
          description: "Complete finished hooks and start stale ones"
```

Short teaching sentence:

> Open the reef. The tide runs in the background. The tide has currents. Currents run jobs.

That is more legible than the current model:

> Open ACE. Axe runs in the background. Axe has lumberjacks. Lumberjacks run chops.

## Why These Names Fit

**`reef` for `ace`** is the strongest finding from both notes. `coral reef` is the canonical phrase, and a reef is a
place you inspect, navigate, and understand as a living system. That matches the TUI better than action words such as
`dive` or command-center words such as `helm`.

**`tide` for `axe`** is the clearest daemon name. Tides are regular, recurring, and predictable; `sase axe` is exactly a
scheduled background subsystem. It also reads naturally in daemon lifecycle commands: `coral tide start`, `coral tide
stop`, `coral tide status`.

**`current` for `lumberjack`** is a good middle layer. A current is a named flow within the water system, which maps
well to `hooks`, `waits`, `checks`, `comments`, and `housekeeping`: each is a recurring stream of work with its own
cadence and state. The only caveat is that `current` can also mean "present state"; under `coral tide current ...`, the
water-flow meaning is clear enough.

**`job` for `chop`** should stay plain. A chop has names, descriptions, logs, status, history, timeouts, manual runs,
and agent/script execution. `job` is the conventional software word users will understand immediately. This is the one
slot where literal language is better than theme.

## Alternatives

| Set | Mapping | When to choose it | Why not primary |
| --- | --- | --- | --- |
| **Flow/Lane/Job** | `reef`, `flow`, `lane`, `job` | If `tide` feels too close to Tide Commander or too themed. | Less coral-specific; `flow` is a heavily overloaded software word. |
| **Keeper/Routine/Task** | `reef`, `keeper`, `routine`, `task` | If you want the daemon to feel like reef maintenance. | `keeper` sounds like a person/role more than a daemon, and `routine` underplays manual foreground runs. |
| **Reel/Angler/Cast** | `reef`, `reel`, `angler`, `cast` | If preserving the current `ace`/`axe` twin aesthetic matters most. | Clever but more distant from daemon/job semantics; shifts from coral to fishing. |

I would no longer recommend **Trawl/Crew/Haul** as a serious option. It has good continuous-work imagery, but trawling
and fishing gear have negative coral-reef associations, including physical reef damage. That is the wrong direction for
a `coral` brand.

## Terms To Avoid

| Term | Why avoid it |
| --- | --- |
| `polyp` | Biologically accurate as a small reef-building unit, but not obvious as something runnable from a CLI. |
| `fragment` / `frag` | Reef-hobby vocabulary; too niche and not clearly executable. |
| `bleach` | Strong negative coral association. |
| `surge` | Suggests spikes, overload, and incidents rather than reliable scheduled work. |
| `helm` | Good control metaphor but a direct Kubernetes collision. |
| `trawl` | Continuous-work imagery, but bad coral/ecology association. |
| `zooxanthellae` | Accurate and unusable. |

## Migration Notes

If the primary set is adopted, the user-facing rename surface should be treated as real migration work:

| Current surface | Future surface |
| --- | --- |
| `sase ace` | `coral reef` |
| `sase axe` | `coral tide` |
| `sase axe lumberjack` | `coral tide current` |
| `sase axe chop` | `coral tide job` |
| `--lumberjack`, `-L` | `--current`, likely keep `-C` only if it does not conflict |
| `axe:` config section | `tide:` |
| `lumberjacks:` config map | `currents:` |
| `chops:` config list | `jobs:` |
| `chop_timeout` / `chop_script_dirs` | `job_timeout` / `job_script_dirs` |
| `~/.sase/axe/lumberjacks/<name>/chops/<job>/` | `~/.coral/tide/currents/<name>/jobs/<job>/` |
| ACE `Axe` tab | Reef `Tide` tab |

For script discovery, keep legacy names as a compatibility fallback for at least one transition period:

1. Exact configured executable name in `tide.job_script_dirs`.
2. `coral_job_<name>` beside the Python executable.
3. `coral_job_<name>` on `PATH`.
4. Legacy `sase_chop_<name>` beside the Python executable.
5. Legacy `sase_chop_<name>` on `PATH`.

Documentation should still use literal operational words: daemon, orchestrator, scheduler loop, job, run, status,
history, log, manual run. The theme should make the product memorable, not hide the contract.

## Caveats

- `reef` is already used in software, including Redocly Reef. As a nested subcommand under `coral`, that is acceptable;
  it would need stronger clearance as a standalone product name.
- `tide` has a nearby AI-agent tool collision: Tide Commander is a visual orchestrator for Claude Code and Codex. This
  argues against marketing the daemon externally as a standalone product named "Tide", but it does not outweigh the
  clarity of `coral tide` as an internal subcommand.
- This note assumes `coral` is already selected. The existing top-level rename note did not clear `coral`; registry,
  GitHub, domain, and trademark checks for the top-level name still need to be done separately.

## Sources Checked

Local:

- `README.md`
- `docs/ace.md`
- `docs/axe.md`
- `src/sase/main/parser_ace.py`
- `src/sase/main/parser.py`
- `src/sase/main/axe_handler.py`
- `sdd/research/202606/sase_rename_research_consolidated.md`

External:

- NOAA, Coral reef ecosystems: https://www.noaa.gov/education/resource-collections/marine-life/coral-reef-ecosystems
- NOAA Tides and Currents glossary/products, tides as periodic water movement: https://tidesandcurrents.noaa.gov/products.html
- NOAA Tides and Currents, currents as water movement: https://tidesandcurrents.noaa.gov/currents_info.html
- NOAA National Ocean Service, coral overfishing and gear damage: https://oceanservice.noaa.gov/facts/coral-overfishing.html
- Redocly Reef: https://redocly.com/reef
- Tide Commander: https://tidecommander.com/

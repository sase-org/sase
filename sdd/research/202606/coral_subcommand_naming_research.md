# Coral Subcommand Naming Research

Date: 2026-06-22

## Question

If `sase` becomes `coral`, what should happen to the `ace` and `axe` names, and what should replace Axe's
`lumberjack` and `chop` vocabulary?

This note assumes the top-level command is already chosen:

```bash
coral ...
```

The goal is not just to find coral-adjacent words. The names need to be easy to type, easy to understand from the
command shape, and close enough to what the feature actually does that a new user does not need to learn a private joke
before they can operate the system.

## Current Semantics

Local docs and code define the four terms this rename needs to preserve:

| Current term | Current role |
| --- | --- |
| `sase ace` | Primary interactive TUI for ChangeSpecs, live agents, notifications, automation, comments, review, and prompt launch. |
| `sase axe` | Background automation daemon for scheduled work, hook/comment/mentor checks, workflow cleanup, `%wait`, digests, and manual foreground runs. |
| `lumberjack` | A named scheduler process/loop with its own interval, state, metrics, and a set of jobs. Default examples: `hooks`, `waits`, `checks`, `comments`, `housekeeping`. |
| `chop` | One executable work unit inside a lumberjack. A chop can be a script or an agent launch, has history/logs, can be run manually, and may have per-job cadence/timeout. |

The most important behavioral fact: `lumberjack` is not just a worker thread, and `chop` is not just a shell script.
The scheduler loop and the job unit both have operator-facing lifecycle, logs, status, history, and manual-run behavior.

## Naming Criteria

1. Keep the common case short: `coral reef`, `coral tide start`, `coral tide job run hook_checks`.
2. Prefer common English over marine-biology precision.
3. Make the noun match the operation: a job should sound runnable; a daemon should sound persistent; the TUI should
   sound like a place to inspect.
4. Avoid terms with negative coral associations such as `bleach`.
5. Avoid obscure accurate terms such as `zooxanthellae`, `cnidaria`, `planula`, and `polyp` unless they provide a large
   clarity win. They do not.
6. Keep pluralization clean in config: `tide.currents.*.jobs`.
7. Preserve room for non-themed names where clarity matters. `job` is better than a cute coral noun for `chop`.

## Coral/Ocean Vocabulary Notes

External sources support a few useful metaphors:

- A coral reef is the visible, living ecosystem built by many small parts. That maps well to the interactive control
  surface where agents, ChangeSpecs, automation, comments, and artifacts are all visible together.
- Tides are periodic movement. That maps naturally to scheduled daemon cycles.
- Currents are water movement, often driven by tides, and can be predictable. That maps well to named recurring work
  streams like `hooks`, `waits`, and `checks`.
- Coral polyps are biologically tempting as the smallest reef-building unit, but `coral tide polyp run ...` is worse
  than `coral tide job run ...` for almost every real user.

## Primary Recommendation

Use this set:

| Current | Recommended | Example | Why |
| --- | --- | --- | --- |
| `ace` | `reef` | `coral reef` | The reef is the visible ecosystem. It is short, natural after `coral`, and broad enough for PRs, agents, automation, prompts, and review. |
| `axe` | `tide` | `coral tide start` | The daemon is interval-driven background movement. `tide` gives the periodic scheduler a memorable but still obvious name. |
| `lumberjack` | `current` | `coral tide current status` | A current is a named flow within the tide. This fits `hooks`, `waits`, `checks`, `comments`, and `housekeeping` better than a worker/person noun. |
| `chop` | `job` | `coral tide job run hook_checks --current hooks` | A chop is exactly a job from the operator's perspective. This is the one place where plain software vocabulary beats the theme. |

Recommended command tree:

```bash
coral reef [QUERY] [options]

coral tide start [options]
coral tide stop [options]
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
          description: "Complete finished hooks and start stale ones, with zombie detection"
```

Recommended script naming:

```text
sase_chop_hook_checks      -> coral_job_hook_checks
sase_chop_error_digest     -> coral_job_error_digest
axe.chop_script_dirs       -> tide.job_script_dirs
```

For migration, keep `sase_chop_*` script discovery as a compatibility fallback for at least one transition period.
The final lookup order can be:

1. Exact configured executable name in `tide.job_script_dirs`.
2. `coral_job_<name>` beside the Python executable.
3. `coral_job_<name>` on `PATH`.
4. Legacy `sase_chop_<name>` beside the Python executable.
5. Legacy `sase_chop_<name>` on `PATH`.

## Why This Set Works

`coral reef` reads as one phrase. A user does not have to remember what ACE stands for, and the term is not too narrow.
`reef` can contain PRs, agents, automation, notifications, comments, prompt stacks, and artifacts without sounding like
only one of those things.

`coral tide` also reads as one phrase. It tells the user that this subsystem moves in the background and returns on a
cadence. It works in daemon lifecycle language:

```bash
coral tide start
coral tide stop
coral tide status
```

`current` is the cleanest replacement for `lumberjack` because it describes a named movement of work rather than a
person. The default names still make sense:

```text
hooks current
waits current
checks current
comments current
housekeeping current
```

`job` is intentionally not a coral noun. The current `chop` concept has enough operator surface that clarity matters
more than theme: jobs have names, descriptions, logs, status, history, timeouts, and manual execution.

The short mental model becomes:

> Open the reef. The tide runs in the background. The tide has currents. Currents run jobs.

That sentence is much easier to teach than the current model:

> Open ACE. Axe runs in the background. Axe has lumberjacks. Lumberjacks run chops.

## Main Caveats

`reef` is used elsewhere in software, including Redocly Reef, a Ceph release name, and CAIDA's older CoralReef package.
As an internal subcommand under `coral`, this is acceptable; as a standalone product name, it would need more clearance.

`tide` has an adjacent AI-agent command-center collision: Tide Commander describes itself as a visual command center
for Claude Code, Codex, and OpenCode agents. This does not make `coral tide` unusable as a nested daemon subcommand, but
it does argue against branding the daemon externally as a standalone product called "Tide".

`current` can also mean "present state". Under `coral tide current ...`, the water-flow meaning is clear enough. If this
ambiguity feels too costly, use the `flow/lane/job` alternative below.

`job` is generic. That is the point. It will be more obvious in CLI help, config, logs, tests, and user support than
`tasklet`, `polyp`, `fragment`, or `feed`.

## Alternative Sets

### Alternative A: More Software-Obvious

```text
ace         -> reef
axe         -> flow
lumberjack  -> lane
chop        -> job
```

Examples:

```bash
coral flow start
coral flow lane list
coral flow lane run hooks
coral flow job run hook_checks --lane hooks
```

This is the best fallback if `tide` feels too close to Tide Commander. It is less coral-specific, but it is highly
legible. `lane` also maps well to a scheduler lane with a fixed interval and a bundle of jobs. The downside is that
`flow` is a very overloaded software word and loses the nice periodic signal that `tide` provides.

### Alternative B: Maintenance-Oriented

```text
ace         -> reef
axe         -> keeper
lumberjack  -> routine
chop        -> task
```

Examples:

```bash
coral keeper start
coral keeper routine list
coral keeper routine run hooks
coral keeper task run hook_checks --routine hooks
```

This reads well if you want the daemon to feel like reef maintenance. It is friendly and obvious. The weakness is that
`keeper` sounds like a person or role rather than a daemon, and `routine` may understate manual foreground runs and
agent-launch jobs.

### Alternative C: Themed But Still Mostly Clear

```text
ace         -> lagoon
axe         -> current
lumberjack  -> stream
chop        -> task
```

Examples:

```bash
coral lagoon
coral current start
coral current stream list
coral current task run hook_checks --stream hooks
```

This keeps more ocean vocabulary in the command tree. I would not choose it first. `lagoon` is less obviously a control
surface than `reef`, and `current status` language becomes awkward.

## Terms I Would Avoid

| Term | Tempting use | Why avoid it |
| --- | --- | --- |
| `polyp` | `chop` | Biologically accurate, operationally unclear, and odd in command examples. |
| `colony` | `lumberjack` or `agent group` | Too broad. It could mean the whole product, an agent family, a project, or a scheduler. |
| `spawn` | `run` or `job` | Has a coral reproduction meaning, but in software it already means process launch and would be too narrow. |
| `fragment` / `frag` | `chop` | Reef hobby term, but too niche and not obviously executable. |
| `atoll` | `ace` | Attractive but less common than `reef`; many users will not know what it means. |
| `lagoon` | `ace` | Usable as an alternate, but too passive for the primary control surface. |
| `surge` | `axe` | Connotes spikes, overload, and incidents. AXE should feel reliable and scheduled. |
| `wave` | `lumberjack` or `chop` | Vague and heavily overloaded in product naming. |
| `bleach` | cleanup/error concept | Strong negative coral association. |
| `zooxanthellae` | anything | Accurate but unusable in a CLI. |

## Migration Notes

If this naming set is adopted, the deprecation path should make aliases first-class for one or more releases:

```text
sase ace                  -> coral reef
sase axe                  -> coral tide
sase axe lumberjack       -> coral tide current
sase axe chop             -> coral tide job
```

Suggested internal rename targets:

| Current internal surface | Future surface |
| --- | --- |
| `axe` config section | `tide` config section |
| `lumberjacks` config map | `currents` config map |
| `chops` config list | `jobs` config list |
| `chop_timeout` | `job_timeout` |
| `chop_script_dirs` | `job_script_dirs` |
| `~/.sase/axe/lumberjacks/<name>/chops/<job>/` | `~/.coral/tide/currents/<name>/jobs/<job>/` |
| `sase_axe_*` metrics | `coral_tide_*` metrics |
| `axe(hooks)-<id>` workflow metadata | `tide(hooks)-<id>` metadata |
| ACE `Axe` tab | Reef `Tide` tab |

One important product-language choice: keep "daemon", "scheduler", "job", "status", "history", and "log" in the
documentation. The theme should make the system easier to remember, not hide the operational contract.

## Final Recommendation

Adopt:

```text
coral reef
coral tide
coral tide current
coral tide job
```

Use `reef/tide/current/job` as the product vocabulary, and use `flow/lane/job` as the fallback if the Tide Commander
collision feels too close for comfort.

## Sources Checked

Local:

- `README.md`
- `docs/ace.md`
- `docs/axe.md`
- `src/sase/main/parser_ace.py`
- `src/sase/default_config.yml`
- `config/sase.schema.json`
- `pyproject.toml`
- `sdd/research/202606/sase_rename_research_consolidated.md`

External:

- NOAA, Coral reef ecosystems: https://www.noaa.gov/education/resource-collections/marine-life/coral-reef-ecosystems
- Smithsonian Ocean, Corals and Coral Reefs: https://ocean.si.edu/ocean-life/invertebrates/corals-and-coral-reefs
- NOAA National Ocean Service, What is a current?: https://oceanservice.noaa.gov/facts/current.html
- NOAA Tides and Currents products glossary snippet for currents and tides: https://tidesandcurrents.noaa.gov/products.html
- NOAA, Our Restless Tides: https://tidesandcurrents.noaa.gov/restles1.html
- CAIDA CoralReef command usage: https://www.caida.org/catalog/software/coralreef/doc/doc/cmd_usage/
- Redocly Reef: https://redocly.com/reef
- Tide Commander docs: https://tidecommander.com/docs

---
status: done
---

Can you help me rewrite the `sase axe` command to make it easier to replicate each periodic check it performs and make
the routines (set of checks implemented every N seconds, where N is specific to the routine---we will call routines
"jacks") configurable?

This is a large piece of work that should be split into phases (parallel if possible). I'll let you decide how many
phases to create, but keep in mind that each phase will be completed by a distinct `claude` instance.

### Glossary

- **jack**: A routine that is configured in a sase.yml file under the `axe` section. Each jack will have a name, a
  schedule (e.g. "every 5 minutes"), and a set of chops (checks) that it performs on that schedule.
- **chop**: A single check performed by a jack. Each jack must have one or more chops associated with it. And EVERY
  distinct check performed by `sase axe` currently should be implemented as a chop. Every chop should be associated with
  exactly one jack.

### CLI Commands

- The current (obsolete) `sase axe` should be renamed to `sase ax` and all of that logic should be quarantined in such a
  way that makes it easy to delete later (once I have confidence in the new implementation). The new functionality will
  use the current command name (`sase axe`). Add a temporary `use_legacy_axe: true` configuration value to the sase.yml
  file in my chezmoi repo. When this field is set to true, the `!x` keymap in the `sase ace` TUI should start/stop the
  legacy `sase ax` command instead of the new `sase axe` command. All of this should be removed once the new `sase axe`
  command is fully implemented and tested (include this cleanup in one of the final phases of the plan).
- The new `sase axe` command should have two sub-commands: `jack` and `chop`.
  - `sase axe jack` should be used to list, monitor, run, and/or manage jacks.
  - `sase axe chop` should be used to list and/or run chops (allowing easy replication of individual checks).
- The new `sase axe` command (when run without sub-commands) should run each jack as a distinct process (or thread, or
  whatever is appropriate) that executes the chops associated with that jack on the schedule defined for that jack. This
  will allow for better isolation and easier management of each jack.

### `sase ace` TUI

- The "AXE" tab should be updated to allow for multiple command output files to be associated with the special axe entry
  (other commands can be run via `!!` and viewed here, but those should work the same as they do now).
- Each jack should have its output logged and should be accessible on this tab by selecting the axe entry and using the
  `ctrl+n` and `ctrl+p` keybindings to cycle through the jacks. The output of each jack should be clearly labeled with
  the name of the jack.

### Configuration

- Configuration for the jacks (defined in a sase.yml) file should be straightforward and intuitive.
- Configuration for chops will be more complex. I'll let you do the heavy-lifting here with regards to the design. Make
  it intuitive and as simple as possible (but NOT simpler).

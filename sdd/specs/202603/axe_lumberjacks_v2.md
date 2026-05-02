---
status: done
---

Can you help me improve upon the recently added `sase axe` lumberjacks / chops functionality (see the
prompts/axe_lumberjacks_v2.md file and related commits)?

- I want every "chop" to just be an executable script, which can be defined anywhere (to start, we will just redefine
  all functionality in this repo, as scripts in the src/sase/scripts/ directory).
- I want the default lumberjack configuration to be moved from code to a new default*config.yml file at the root of this
  repo. ALL default configuration across the project should be moved to this file. We will merge this default
  configuration with the user configuration defined in the user's `sase.yml` file (with user configuration taking
  precedence) in the same way that we do for `sase*\*.yml` files.
- Remove the `--exclude-decorator` option from the pyvision target in the Justfile file (we shouldn't be using that
  decorator anymore).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.

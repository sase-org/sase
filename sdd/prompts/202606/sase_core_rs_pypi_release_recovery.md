---
plan: sdd/tales/202606/sase_core_rs_pypi_release_recovery.md
---
 I just merged the release-plz PR that was supposed to release version 0.1.1 of the sase-core-rs package. GitHub Actions just finished for that PR. Can you help me verify that the new 0.1.1 version of this package has been properly published? If not, fix the problem. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.


### Additional Requirements

- It doesn't look like the https://pypi.org/pypi/sase-core-rs project has been created yet. Do we need to use the `twine` command to upload an initial version maybe?
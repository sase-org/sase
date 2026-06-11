---
plan: sdd/tales/202606/sase_pypi_015_trusted_publishing.md
---
 Submitting PR #164 should have released version 0.1.5 of sase to PyPI, but it failed (see the error message below). sase is already configured in PyPI (see the configuration used below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.


### PyPI Config
```
Repository: sase-org/sase
Workflow: publish.yml
Environment name: pypi
```

### GitHub Actions Error
```
Error: Trusted publishing exchange failure: 
Token request failed: the server refused the request for the following reasons:

* `invalid-publisher`: valid token, but no corresponding publisher (Publisher with matching claims was not found)

This generally indicates a trusted publisher configuration error, but could
also indicate an internal error on GitHub or PyPI's part.


The claims rendered below are **for debugging purposes only**. You should **not**
use them to configure a trusted publisher unless they already match your expectations.

If a claim is not present in the claim set, then it is rendered as `MISSING`.

* `sub`: `repo:sase-org/sase:environment:pypi`
* `repository`: `sase-org/sase`
* `repository_owner`: `sase-org`
* `repository_owner_id`: `263703557`
* `workflow_ref`: `sase-org/sase/.github/workflows/release.yml@refs/heads/master`
* `job_workflow_ref`: `sase-org/sase/.github/workflows/release.yml@refs/heads/master`
* `ref`: `refs/heads/master`
* `environment`: `pypi`

See https://docs.pypi.org/trusted-publishers/troubleshooting/ for more help.
```
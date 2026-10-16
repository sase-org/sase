---
title: Install and set up SASE
description:
  Install SASE, confirm the command works, and check that an agent provider is ready.
search:
  boost: 2
---

# Install and set up SASE

This tutorial installs SASE and prepares one authenticated provider for your first run.

## Before you start

You need Linux or macOS, Python 3.12 or newer, [`uv`](https://docs.astral.sh/uv/), and
Git.

## 1. Install SASE

Install the SASE command-line tool:

<!-- BEGIN GENERATED: install-command -->
<!-- tutorial-test: skip installs the published package from PyPI -->

```bash
uv tool install "sase>=0.18"
```

<!-- END GENERATED: install-command -->

The version floor makes the install fail if the required release is not available.

## 2. Confirm the installation

Print the installed SASE and core versions:

```bash
sase version
```

The command prints version information for SASE and its core extension.

## 3. Check your provider

Install and authenticate one supported agent CLI, then check that SASE can use it:

<!-- tutorial-test: skip depends on a provider installed and authenticated by the reader -->

```bash
sase doctor
```

If the doctor reports a missing provider or authentication problem, follow the setup
steps in
[Installing and authenticating agent providers](../reference/providers/agent-clis.md),
then run the check again.

## 4. Add shell completion (optional)

If you want tab completion in your shell, run:

<!-- tutorial-test: skip writes shell startup configuration -->

```bash
sase completion install
```

## You have SASE ready for a first run

You have installed SASE and checked that it can find an authenticated provider.

## Next

- [Run your first agent](first-run.md)
- [Shell completion](../reference/integrations/completion.md)

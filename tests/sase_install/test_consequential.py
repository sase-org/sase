"""Consequential-change classification and the confirmation policy."""

from __future__ import annotations

from pathlib import Path

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_plan, install_state


def _pypi_plan(
    tmp_path: Path,
    *,
    host: tuple[str, str | None] | None = ("editable", None),
    plugins: tuple[tuple[str, str, str | None], ...] = (),
    core: tuple[str, str | None] | None = ("local", "0.37.0"),
    options: install_plan.PlanOptions | None = None,
) -> install_plan.InstallPlan:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, _ = kit.make_tool_env(
        tmp_path, host=host, plugins=plugins, core=core, checkout=checkout
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI(
        {
            "sase": "0.17.1",
            "sase-core-rs": "0.35.4",
            "sase-github": "0.4.2",
            "sase-telegram": "0.4.26",
        }
    )
    return install_plan.build_plan(
        options=options or install_plan.PlanOptions(mode="pypi"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )


def _kinds(plan: install_plan.InstallPlan) -> dict[str, str]:
    return {row.name: row.kind for row in plan.rows}


def test_mode_flip_is_consequential(tmp_path: Path) -> None:
    plan = _pypi_plan(tmp_path)
    assert _kinds(plan)["sase"] == "to-pypi"
    host = next(row for row in plan.rows if row.role == "host")
    assert host.consequential
    assert plan.consequential


def test_local_core_downgrade_is_consequential(tmp_path: Path) -> None:
    plan = _pypi_plan(tmp_path)
    core = next(row for row in plan.rows if row.role == "core")
    assert core.kind == "to-pypi"
    assert core.consequential
    assert "downgrade" in core.note


def test_same_source_upgrade_is_not_consequential(tmp_path: Path) -> None:
    plan = _pypi_plan(
        tmp_path,
        host=("pypi", "0.17.0"),
        core=("pypi", "0.35.4"),
        plugins=(("sase-github", "pypi", "0.2.0"),),
    )
    assert _kinds(plan)["sase"] == "upgrade"
    assert not plan.rows[0].consequential
    assert _kinds(plan)["sase-github"] == "upgrade"
    assert _kinds(plan)["sase-core-rs"] == "keep"
    assert not plan.consequential
    assert plan.noop is False


def test_noop_when_everything_current(tmp_path: Path) -> None:
    plan = _pypi_plan(
        tmp_path,
        host=("pypi", "0.17.1"),
        core=("pypi", "0.35.4"),
        plugins=(
            ("sase-github", "pypi", "0.4.2"),
            ("sase-telegram", "pypi", "0.4.26"),
        ),
    )
    assert plan.noop
    assert not plan.consequential


def test_force_defeats_noop(tmp_path: Path) -> None:
    plan = _pypi_plan(
        tmp_path,
        host=("pypi", "0.17.1"),
        core=("pypi", "0.35.4"),
        options=install_plan.PlanOptions(mode="pypi", force=True),
    )
    assert not plan.noop


def test_python_change_is_consequential_only_with_existing_env(
    tmp_path: Path,
) -> None:
    plan = _pypi_plan(
        tmp_path,
        host=("pypi", "0.17.1"),
        core=("pypi", "0.35.4"),
        options=install_plan.PlanOptions(mode="pypi", python="3.13"),
    )
    assert plan.python.change
    assert plan.python.target == "3.13"
    assert plan.consequential
    assert not plan.noop


def test_host_retarget_is_consequential(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    other = tmp_path / "other-checkout"
    other.mkdir()
    tool_dir, _ = kit.make_tool_env(
        tmp_path, host=("editable", str(other)), checkout=checkout
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="dev"),
        state=state,
        checkout_root=checkout,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )
    host = next(row for row in plan.rows if row.role == "host")
    assert host.kind == "retarget"
    assert host.consequential


def _entry_run(
    tmp_path: Path,
    monkeypatch: object,
    args: list[str],
    *,
    stdin: kit.FakeStdin | None = None,
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    # An editable host flipping to PyPI: consequential, so confirm paths run.
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    env = kit.make_env(tmp_path, **(env_extra or {}))
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.35.4"})
    return kit.run_entry(
        entry,
        args,
        env=env,
        stdin=stdin,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )


def test_non_tty_without_yes_prints_plan_and_exits_2(
    tmp_path: Path, monkeypatch: object
) -> None:
    exit_code, out, err = _entry_run(
        tmp_path,
        monkeypatch,
        ["pypi", "--version", "0.18.0"],
        stdin=kit.FakeStdin(tty=False),
    )
    assert exit_code == 2
    assert "just install" in out  # the plan is printed first
    assert "needs -y without a terminal" in err


def test_non_tty_with_yes_runs_past_confirm(
    tmp_path: Path, monkeypatch: object
) -> None:
    from tests._sase_install_testkit import install_run

    def _boom(argv: object, **kwargs: object) -> object:
        return install_run.RunnerResult(returncode=1, stdout="", stderr="boom")

    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    env = kit.make_env(tmp_path)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.35.4"})
    exit_code, _, err = kit.run_entry(
        entry,
        ["pypi", "--version", "0.18.0", "-y"],
        env=env,
        stdin=kit.FakeStdin(tty=False),
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
        command_runner=_boom,
    )
    assert exit_code == 1  # the stubbed swap fails, so the pipeline fails
    assert "Swap failed" in err
    assert "log:" in err
    assert "to restore the previous install, run:" in err


def test_tty_consequential_prompts_and_decline_cancels(
    tmp_path: Path, monkeypatch: object
) -> None:
    exit_code, _, err = _entry_run(
        tmp_path,
        monkeypatch,
        ["pypi", "--version", "0.18.0"],
        stdin=kit.FakeStdin("n\n", tty=True),
    )
    assert exit_code == 1
    assert "Proceed? [y/N]" in err
    assert "cancelled" in err


def test_tty_consequential_accept_reaches_pipeline(
    tmp_path: Path, monkeypatch: object
) -> None:
    from tests._sase_install_testkit import install_run

    def _boom(argv: object, **kwargs: object) -> object:
        return install_run.RunnerResult(returncode=1, stdout="", stderr="boom")

    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    env = kit.make_env(tmp_path)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.35.4"})
    exit_code, _, err = kit.run_entry(
        entry,
        ["pypi", "--version", "0.18.0"],
        env=env,
        stdin=kit.FakeStdin("y\n", tty=True),
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
        command_runner=_boom,
    )
    assert exit_code == 1
    assert "Swap failed" in err


def test_tty_nonconsequential_skips_prompt(tmp_path: Path, monkeypatch: object) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(
        tmp_path,
        host=("pypi", "0.17.1"),
        core=("pypi", "0.35.4"),
        checkout=checkout,
    )
    env = kit.make_env(tmp_path)
    lookup = kit.FakePyPI({"sase": "0.18.0", "sase-core-rs": "0.35.4"})

    class _ExplodingStdin(kit.FakeStdin):
        def readline(self, *args: object, **kwargs: object) -> str:
            raise AssertionError("must not prompt for a non-consequential plan")

    from tests._sase_install_testkit import install_run

    def _boom(argv: object, **kwargs: object) -> object:
        return install_run.RunnerResult(returncode=1, stdout="", stderr="boom")

    exit_code, _, err = kit.run_entry(
        entry,
        ["pypi"],
        env=env,
        stdin=_ExplodingStdin(tty=True),
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
        command_runner=_boom,
    )
    assert exit_code == 1
    assert "Swap failed" in err

"""Entry-point flows: flags, modes, quiet/JSON output, and exit codes."""

from __future__ import annotations

import json
from pathlib import Path

import tests._sase_install_testkit as kit


def _harness(
    tmp_path: Path,
    monkeypatch: object,
    *,
    host: tuple[str, str | None] | None = ("editable", None),
    core: tuple[str, str | None] | None = ("local", "0.37.0"),
    plugins: tuple[tuple[str, str, str | None], ...] = (),
    versions: dict[str, str] | None = None,
) -> tuple[object, dict[str, str], Path, Path, Path, object]:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(
        tmp_path, host=host, core=core, plugins=plugins, checkout=checkout
    )
    env = kit.make_env(tmp_path)
    lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.37.0", **(versions or {})}
    )
    context = (entry, env, checkout, tool_dir, bin_dir, lookup)
    return context


def test_pypi_dry_run_plan_to_stdout(tmp_path: Path, monkeypatch: object) -> None:
    entry, env, checkout, tool_dir, bin_dir, lookup = _harness(tmp_path, monkeypatch)
    exit_code, out, err = kit.run_entry(
        entry,
        ["pypi", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "just install" in out
    assert "prerequisites:" in out
    assert err == ""


def test_quiet_prints_only_summary(tmp_path: Path, monkeypatch: object) -> None:
    entry, env, checkout, tool_dir, bin_dir, lookup = _harness(tmp_path, monkeypatch)
    exit_code, out, _ = kit.run_entry(
        entry,
        ["pypi", "-n", "-q"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert len(out.splitlines()) == 1
    assert out.startswith("just install: ")


def test_json_prints_only_json(tmp_path: Path, monkeypatch: object) -> None:
    entry, env, checkout, tool_dir, bin_dir, lookup = _harness(tmp_path, monkeypatch)
    exit_code, out, err = kit.run_entry(
        entry,
        ["pypi", "-n", "-j"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert err == ""
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert doc["dry_run"] is True
    assert doc["outcome"] == "plan"


def test_dev_dry_run_uses_dev_prog(tmp_path: Path, monkeypatch: object) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(
        tmp_path, host=("pypi", "0.17.1"), checkout=checkout
    )
    env = kit.make_env(tmp_path)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    exit_code, out, _ = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "just install-dev" in out


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: object) -> None:
    entry, env, checkout, tool_dir, bin_dir, lookup = _harness(tmp_path, monkeypatch)
    before = sorted(p.name for p in tool_dir.rglob("*"))
    exit_code, _, _ = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    after = sorted(p.name for p in tool_dir.rglob("*"))
    assert before == after
    overrides = Path(env["SASE_HOME"]) / "uv" / "editable-overrides.txt"
    assert not overrides.exists()


def test_missing_uv_is_exit_2(tmp_path: Path, monkeypatch: object) -> None:
    from tests._sase_install_testkit import install_env

    entry = kit.load_entry()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        install_env,
        "probe_uv",
        lambda: install_env.ProbeResult(name="uv", ok=False, detail="no uv"),
    )
    env = kit.make_env(tmp_path)
    exit_code, out, err = kit.run_entry(entry, ["pypi", "-n"], env=env)
    assert exit_code == 2
    assert out == ""
    assert "no uv" in err


def test_missing_cargo_warns_on_dry_run_but_fails_real_run(
    tmp_path: Path, monkeypatch: object
) -> None:
    from tests._sase_install_testkit import install_env

    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        install_env,
        "probe_cargo",
        lambda: install_env.ProbeResult(
            name="cargo", ok=False, detail="install rustup, or use `just install`"
        ),
    )
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    env = kit.make_env(tmp_path)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    exit_code, out, _ = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "install rustup" in out
    exit_code, _, err = kit.run_entry(
        entry,
        ["dev", "-y"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 2
    assert "install rustup" in err


def test_help_lists_modes() -> None:
    entry = kit.load_entry()
    parser = entry.build_parser()
    assert set(parser._subparsers._group_actions[0].choices) == {"pypi", "dev"}
    dev_parser = parser._subparsers._group_actions[0].choices["dev"]
    option_strings = [action.option_strings for action in dev_parser._actions]
    flat = [opt for group in option_strings for opt in group]
    for flag in (
        "-n",
        "--dry-run",
        "-y",
        "--yes",
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "-j",
        "--json",
        "--with",
        "--python",
        "--force",
        "--keep-plugin-sources",
        "--sync",
    ):
        assert flag in flat, flag


def test_sync_flag_fetches_and_reports(tmp_path: Path, monkeypatch: object) -> None:
    # The --sync gate landed with dev-core-prep: a dry run fetches every
    # checkout the plan will use and prints the report (here the plain-dir
    # fixture checkout is skipped, and the missing core becomes a clone row).
    entry, env, checkout, tool_dir, bin_dir, lookup = _harness(tmp_path, monkeypatch)
    exit_code, out, _ = kit.run_entry(
        entry,
        ["dev", "-n", "--sync"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "--sync" in out
    assert "skipping" in out


def test_version_compare_orders_releases() -> None:
    from tests._sase_install_testkit import install_pypi

    assert install_pypi.compare_versions("0.17.1", "0.17.2") < 0
    assert install_pypi.compare_versions("0.37.0", "0.35.4") > 0
    assert install_pypi.compare_versions("1.2", "1.2.0") == 0
    assert install_pypi.compare_versions("1.0rc1", "1.0") < 0
    assert install_pypi.compare_versions("1.0", "1.0.post1") < 0
    assert install_pypi.versions_equal("0.17.1", "0.17.1")

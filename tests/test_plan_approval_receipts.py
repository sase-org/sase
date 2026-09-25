"""Receipt storage for gateless plan approvals."""

from __future__ import annotations

from pathlib import Path

from sase.plan_approval_receipts import (
    DirectApprovalReceipt,
    delete_direct_approval_receipt,
    iter_direct_approval_receipts,
    read_direct_approval_receipt,
    receipt_path_for,
    write_direct_approval_receipt,
)


def _receipt(plan_path: Path, **overrides: object) -> DirectApprovalReceipt:
    fields: dict[str, object] = {
        "plan_path": str(plan_path),
        "action": "tale",
        "approved_at": "2026-09-24T12:00:00+00:00",
        "source": "cli",
        "route": "standalone",
        "project": "demo",
    }
    fields.update(overrides)
    return DirectApprovalReceipt(**fields)  # type: ignore[arg-type]


def test_receipt_roundtrip(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    local_plan = home / "plans" / "202609" / "foo.md"
    local_plan.parent.mkdir(parents=True)
    local_plan.write_text("x", encoding="utf-8")

    path = write_direct_approval_receipt(_receipt(local_plan))
    assert path == receipt_path_for(local_plan)
    assert path.parent.name == "202609"

    loaded = read_direct_approval_receipt(local_plan)
    assert loaded is not None
    assert loaded.plan_path == str(local_plan)
    assert loaded.action == "tale"
    assert loaded.route == "standalone"
    assert loaded.schema_version == 1


def test_receipt_delete_removes_it_and_tolerates_absence(
    tmp_path: Path, monkeypatch
) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    local_plan = home / "plans" / "202609" / "foo.md"
    local_plan.parent.mkdir(parents=True)
    local_plan.write_text("x", encoding="utf-8")
    write_direct_approval_receipt(_receipt(local_plan))

    delete_direct_approval_receipt(local_plan)
    assert read_direct_approval_receipt(local_plan) is None
    assert not receipt_path_for(local_plan).exists()

    delete_direct_approval_receipt(local_plan)


def test_receipt_missing_returns_none(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    assert read_direct_approval_receipt(home / "plans" / "202609" / "nope.md") is None


def test_receipt_corrupt_returns_none(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    local_plan = home / "plans" / "202609" / "bad.md"
    local_plan.parent.mkdir(parents=True)
    local_plan.write_text("x", encoding="utf-8")
    receipt_path = receipt_path_for(local_plan)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{not json", encoding="utf-8")
    assert read_direct_approval_receipt(local_plan) is None


def test_iter_receipts(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    plans = []
    for name in ("aaa.md", "bbb.md"):
        plan = home / "plans" / "202609" / name
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("x", encoding="utf-8")
        plans.append(plan)
    for plan in plans:
        write_direct_approval_receipt(_receipt(plan))
    # A corrupt file is skipped, not fatal.
    corrupt = receipt_path_for(plans[0]).parent / "corrupt.json"
    corrupt.write_text("{oops", encoding="utf-8")

    receipts = iter_direct_approval_receipts()
    assert {receipt.plan_path for receipt in receipts} == {str(plan) for plan in plans}

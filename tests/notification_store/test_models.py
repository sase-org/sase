from sase.notifications.models import Notification


class TestNotificationModel:
    """Tests for the Notification dataclass."""

    def test_required_fields(self) -> None:
        n = Notification(id="abc", timestamp="2025-01-01T00:00:00", sender="test")
        assert n.id == "abc"
        assert n.sender == "test"

    def test_default_values(self) -> None:
        n = Notification(id="abc", timestamp="2025-01-01T00:00:00", sender="test")
        assert n.notes == []
        assert n.files == []
        assert n.action is None
        assert n.action_data == {}
        assert n.read is False
        assert n.dismissed is False

    def test_all_fields(self) -> None:
        n = Notification(
            id="abc",
            timestamp="2025-01-01T00:00:00",
            sender="crs",
            notes=["line1", "line2"],
            files=["/tmp/a.py"],
            action="HITL",
            action_data={"key": "value"},
            read=True,
            dismissed=True,
        )
        assert n.notes == ["line1", "line2"]
        assert n.action == "HITL"
        assert n.action_data == {"key": "value"}
        assert n.read is True
        assert n.dismissed is True

    def test_silent_field(self) -> None:
        n = Notification(
            id="abc",
            timestamp="2025-01-01T00:00:00",
            sender="crs",
            silent=True,
        )
        assert n.silent is True

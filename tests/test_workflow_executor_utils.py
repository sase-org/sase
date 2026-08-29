"""Tests for parse_bash_output in workflow_executor_utils."""

from sase.xprompt.workflow_executor_utils import parse_bash_output


class TestParseBashOutput:
    """Tests for parse_bash_output function."""

    def test_parse_json_array(self) -> None:
        """Test parsing JSON array output."""
        output = "[1, 2, 3]"
        result = parse_bash_output(output)
        assert result == [1, 2, 3]

    def test_parse_json_with_leading_control_chars(self) -> None:
        """Test that leading control characters (e.g., bell) don't prevent JSON parsing."""
        output = '\x07\x07\x07{"success": true, "pr_url": "http://example.com"}'
        result = parse_bash_output(output)
        assert result == {"success": True, "pr_url": "http://example.com"}

    def test_parse_key_value(self) -> None:
        """Test parsing key=value output."""
        output = "foo=bar\nbaz=qux"
        result = parse_bash_output(output)
        assert result == {"foo": "bar", "baz": "qux"}

    def test_parse_plain_text_fallback(self) -> None:
        """Test plain text falls back to _output key."""
        output = "just some text"
        result = parse_bash_output(output)
        assert result == {"_output": "just some text"}

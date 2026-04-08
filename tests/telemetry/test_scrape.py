"""Tests for ``sase.telemetry.scrape`` — Prometheus text parser + HTTP client."""

from unittest.mock import MagicMock, patch

from sase.telemetry.scrape import (
    MetricSample,
    check_reachable,
    compute_percentiles,
    format_samples_as_json,
    format_samples_as_prometheus,
    _parse_prometheus_text as parse_prometheus_text,
    scrape,
)

# ---------------------------------------------------------------------------
# Sample Prometheus text fixtures
# ---------------------------------------------------------------------------
SIMPLE_TEXT = """\
# HELP sase_agent_runs_total Total agent runs
# TYPE sase_agent_runs_total counter
sase_agent_runs_total{llm_provider="claude",status="ok",workflow=""} 42
sase_agent_runs_total{llm_provider="claude",status="error",workflow=""} 3
# TYPE sase_agent_active gauge
sase_agent_active{llm_provider="claude",project="sase"} 2
"""

HISTOGRAM_TEXT = """\
# HELP sase_agent_run_duration_seconds Agent run duration
# TYPE sase_agent_run_duration_seconds histogram
sase_agent_run_duration_seconds_bucket{llm_provider="claude",workflow="",le="10"} 5
sase_agent_run_duration_seconds_bucket{llm_provider="claude",workflow="",le="30"} 15
sase_agent_run_duration_seconds_bucket{llm_provider="claude",workflow="",le="60"} 25
sase_agent_run_duration_seconds_bucket{llm_provider="claude",workflow="",le="120"} 35
sase_agent_run_duration_seconds_bucket{llm_provider="claude",workflow="",le="300"} 40
sase_agent_run_duration_seconds_bucket{llm_provider="claude",workflow="",le="+Inf"} 42
sase_agent_run_duration_seconds_count{llm_provider="claude",workflow=""} 42
sase_agent_run_duration_seconds_sum{llm_provider="claude",workflow=""} 1890.5
"""

NO_LABELS_TEXT = """\
# TYPE sase_axe_lumberjacks_active gauge
sase_axe_lumberjacks_active 3
"""


# ---------------------------------------------------------------------------
# parse_prometheus_text tests
# ---------------------------------------------------------------------------
class TestParsePrometheusText:
    def test_parses_counter_samples(self) -> None:
        samples = parse_prometheus_text(SIMPLE_TEXT)
        counters = [s for s in samples if s.metric_type == "counter"]
        assert len(counters) == 2
        assert counters[0].name == "sase_agent_runs_total"
        assert counters[0].labels["status"] == "ok"
        assert counters[0].value == 42.0

    def test_parses_gauge_samples(self) -> None:
        samples = parse_prometheus_text(SIMPLE_TEXT)
        gauges = [s for s in samples if s.metric_type == "gauge"]
        assert len(gauges) == 1
        assert gauges[0].name == "sase_agent_active"
        assert gauges[0].value == 2.0

    def test_parses_histogram_buckets(self) -> None:
        samples = parse_prometheus_text(HISTOGRAM_TEXT)
        buckets = [s for s in samples if s.name.endswith("_bucket")]
        assert len(buckets) == 6
        assert all(s.metric_type == "histogram" for s in buckets)

    def test_parses_histogram_count_and_sum(self) -> None:
        samples = parse_prometheus_text(HISTOGRAM_TEXT)
        count = [s for s in samples if s.name.endswith("_count")]
        total = [s for s in samples if s.name.endswith("_sum")]
        assert len(count) == 1
        assert count[0].value == 42.0
        assert len(total) == 1
        assert total[0].value == 1890.5

    def test_no_labels(self) -> None:
        samples = parse_prometheus_text(NO_LABELS_TEXT)
        assert len(samples) == 1
        assert samples[0].labels == {}
        assert samples[0].value == 3.0

    def test_empty_input(self) -> None:
        assert parse_prometheus_text("") == []

    def test_comments_only(self) -> None:
        assert parse_prometheus_text("# HELP foo\n# just a comment\n") == []

    def test_malformed_lines_skipped(self) -> None:
        text = "not a valid line\nsase_foo 42\n"
        samples = parse_prometheus_text(text)
        assert len(samples) == 1
        assert samples[0].name == "sase_foo"

    def test_invalid_value_skipped(self) -> None:
        text = "# TYPE sase_foo counter\nsase_foo notanumber\n"
        samples = parse_prometheus_text(text)
        assert len(samples) == 0


# ---------------------------------------------------------------------------
# compute_percentiles tests
# ---------------------------------------------------------------------------
class TestComputePercentiles:
    def test_computes_percentiles_from_buckets(self) -> None:
        samples = parse_prometheus_text(HISTOGRAM_TEXT)
        buckets = [s for s in samples if s.name.endswith("_bucket")]
        pcts = compute_percentiles(buckets)
        assert "p50" in pcts
        assert "p95" in pcts
        assert "p99" in pcts
        # p50: 50% of 42 = 21 → falls in the 60 bucket
        assert pcts["p50"] == 60
        # p95: 95% of 42 = 39.9 → falls in the 300 bucket
        assert pcts["p95"] == 300

    def test_empty_buckets(self) -> None:
        assert compute_percentiles([]) == {}

    def test_zero_total(self) -> None:
        samples = [
            MetricSample(
                name="foo_bucket",
                labels={"le": "10"},
                value=0.0,
                metric_type="histogram",
            ),
            MetricSample(
                name="foo_bucket",
                labels={"le": "+Inf"},
                value=0.0,
                metric_type="histogram",
            ),
        ]
        assert compute_percentiles(samples) == {}


# ---------------------------------------------------------------------------
# format helpers tests
# ---------------------------------------------------------------------------
class TestFormatHelpers:
    def test_format_as_json(self) -> None:
        samples = [
            MetricSample(
                name="foo", labels={"a": "1"}, value=42.0, metric_type="counter"
            )
        ]
        result = format_samples_as_json(samples)
        assert '"name": "foo"' in result
        assert '"value": 42.0' in result

    def test_format_as_prometheus(self) -> None:
        samples = [
            MetricSample(
                name="foo", labels={"a": "1"}, value=42.0, metric_type="counter"
            ),
            MetricSample(name="bar", labels={}, value=7.0, metric_type="gauge"),
        ]
        result = format_samples_as_prometheus(samples)
        assert 'foo{a="1"} 42.0' in result
        assert "bar 7.0" in result


# ---------------------------------------------------------------------------
# scrape() HTTP tests
# ---------------------------------------------------------------------------
class TestScrape:
    def test_scrape_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = SIMPLE_TEXT.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "sase.telemetry.scrape.urllib.request.urlopen", return_value=mock_resp
        ):
            samples = scrape("http://localhost:9091/metrics")

        assert len(samples) == 3

    def test_scrape_unreachable(self) -> None:
        import urllib.error

        with patch(
            "sase.telemetry.scrape.urllib.request.urlopen",
            side_effect=urllib.error.URLError("unreachable"),
        ):
            samples = scrape("http://localhost:9091/metrics")

        assert samples == []


# ---------------------------------------------------------------------------
# check_reachable() tests
# ---------------------------------------------------------------------------
class TestCheckReachable:
    def test_reachable(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "sase.telemetry.scrape.urllib.request.urlopen", return_value=mock_resp
        ):
            assert check_reachable("http://localhost:9091/metrics") is True

    def test_unreachable(self) -> None:
        import urllib.error

        with patch(
            "sase.telemetry.scrape.urllib.request.urlopen",
            side_effect=urllib.error.URLError("unreachable"),
        ):
            assert check_reachable("http://localhost:9091/metrics") is False

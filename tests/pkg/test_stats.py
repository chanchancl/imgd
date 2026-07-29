from hypothesis import given, settings
from hypothesis import strategies as st

from pkg.stats import RequestStatsCollector, _percentile

# ==== Property-based tests ====


@given(st.lists(st.floats(0.0, 10000.0), min_size=1, max_size=100))
@settings(max_examples=1000)
def test_percentile_monotonic(values):
    """P50 ≤ P90 ≤ P99 恒成立。"""
    s = sorted(values)
    p50 = _percentile(s, 50)
    p90 = _percentile(s, 90)
    p99 = _percentile(s, 99)
    assert p50 <= p90 <= p99


@given(st.lists(st.floats(0.0, 10000.0), min_size=1, max_size=100))
@settings(max_examples=1000)
def test_percentile_range(values):
    """百分位值必定在 [min, max] 范围内。"""
    s = sorted(values)
    for p in (50, 90, 99):
        result = _percentile(s, p)
        assert s[0] <= result <= s[-1]


@given(st.lists(st.floats(0.0, 10000.0), max_size=50))
@settings(max_examples=1000)
def test_collector_count_increases(values):
    """record 调用后 total_requests 必须递增。"""
    c = RequestStatsCollector()
    prev = 0
    for v in values:
        c.record("POST", "/query/test", v)
        stats = c.get_stats()
        assert stats["total_requests"] == prev + 1
        prev = stats["total_requests"]


class TestPercentile:
    def test_empty(self):
        assert _percentile([], 50) == 0.0

    def test_single(self):
        assert _percentile([5.0], 50) == 5.0

    def test_two_elements(self):
        assert _percentile([1.0, 2.0], 50) == 1.5

    def test_ten_elements(self):
        data = sorted([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        assert _percentile(data, 50) == 5.5
        assert _percentile(data, 90) == 9.1
        assert _percentile(data, 99) == 9.91

    def test_all_same_value(self):
        data = [3.0] * 5
        assert _percentile(data, 50) == 3.0
        assert _percentile(data, 99) == 3.0


class TestRequestStatsCollector:
    def test_empty(self):
        collector = RequestStatsCollector()
        stats = collector.get_stats()
        assert stats["total_requests"] == 0
        assert stats["overall"]["count"] == 0

    def test_record_and_get_stats(self):
        collector = RequestStatsCollector()
        collector.record("POST", "/query/match", 10.0)
        collector.record("POST", "/query/match", 20.0)
        collector.record("GET", "/query/author", 5.0)

        stats = collector.get_stats()
        assert stats["total_requests"] == 3
        o = stats["overall"]
        assert o["count"] == 3
        assert o["min"] == 5.0
        assert o["max"] == 20.0
        assert o["avg"] == 11.67
        assert o["p50"] <= o["p90"] <= o["p99"]

    def test_per_endpoint_breakdown(self):
        collector = RequestStatsCollector()
        collector.record("POST", "/query/a", 10.0)
        collector.record("POST", "/query/a", 30.0)
        collector.record("POST", "/query/b", 20.0)

        stats = collector.get_stats()
        endpoints = stats["per_endpoint"]
        assert len(endpoints) == 2
        assert "POST /query/a" in endpoints
        assert "POST /query/b" in endpoints
        assert endpoints["POST /query/a"]["count"] == 2

    def test_uptime(self):
        collector = RequestStatsCollector()
        stats = collector.get_stats()
        assert stats["uptime_seconds"] >= 0

import datetime
from unittest.mock import patch

from pkg.models import TitlesCache


class TestTitlesCache:
    def test_to_dict(self):
        ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        cache = TitlesCache(createTime=ts, titles=["a", "b"])
        d = cache.to_dict()
        assert d["titles"] == ["a", "b"]
        assert "2025-01-01" in d["createTime"]

    def test_from_dict(self):
        d = {"createTime": "2025-01-01T00:00:00+00:00", "titles": ["x", "y"]}
        cache = TitlesCache.from_dict(d)
        assert cache.titles == ["x", "y"]

    def test_roundtrip(self):
        ts = datetime.datetime.now(tz=datetime.timezone.utc)
        cache = TitlesCache(createTime=ts, titles=["hello", "world"])
        restored = TitlesCache.from_dict(cache.to_dict())
        assert restored.titles == cache.titles

    @patch("pkg.models.JUST_LOAD", False)
    def test_is_valid_expired(self):
        ts = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=2)
        cache = TitlesCache(createTime=ts, titles=[])
        assert cache.is_valid(max_age_days=1) is False

    def test_is_valid_fresh(self):
        ts = datetime.datetime.now(tz=datetime.timezone.utc)
        cache = TitlesCache(createTime=ts, titles=[])
        assert cache.is_valid(max_age_days=1) is True

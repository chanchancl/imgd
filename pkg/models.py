"""数据模型 — TitlesCache, CacheSnapshot"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from pkg.constants import JUST_LOAD, now_cst


@dataclass(frozen=True)
class CacheSnapshot:
    """缓存一致性快照，无需加锁安全读取。"""

    titles: list[str]
    trigram_index: dict[str, frozenset[int]]
    bigram_index: dict[str, frozenset[int]]
    authors: list[str]
    author_set: set[str]

    @property
    def all_indices(self) -> list[int]:
        """所有标题索引列表（全量扫描用）"""
        return list(range(len(self.titles)))


@dataclass
class TitlesCache:
    createTime: datetime.datetime
    titles: list[str]

    def to_dict(self) -> dict:
        """JSON 序列化"""
        return {"createTime": self.createTime.isoformat(), "titles": self.titles}

    @classmethod
    def from_dict(cls, data: dict) -> "TitlesCache":
        return cls(
            createTime=datetime.datetime.fromisoformat(data["createTime"]),
            titles=data.get("titles", []),
        )

    def save(self, filepath: str | Path) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)

    @classmethod
    def load(cls, filepath: str | Path) -> "TitlesCache":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def is_valid(self, max_age_days: int = 1) -> bool:
        if JUST_LOAD:
            return True
        return now_cst() - self.createTime < datetime.timedelta(days=max_age_days)

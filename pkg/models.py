"""数据模型 — TitlesCache, CacheSnapshot"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from config import JUST_LOAD
from pkg.constants import now_cst


@dataclass(frozen=True)
class CacheSnapshot:
    """缓存的一致性快照，无需加锁即可安全读取。

    Python GIL 保证引用读取的原子性，CacheStore._update() 整体替换引用。
    """

    titles: list[str]
    trigram_index: dict[str, frozenset[int]]
    bigram_index: dict[str, frozenset[int]]
    authors: list[str]
    author_set: set[str]

    @property
    def all_indices(self) -> list[int]:
        """全量扫描：所有标题索引的列表。"""
        return list(range(len(self.titles)))


@dataclass
class TitlesCache:
    createTime: datetime.datetime
    titles: list[str]

    def to_dict(self) -> dict:
        """转换为字典用于 JSON 序列化"""
        return {"createTime": self.createTime.isoformat(), "titles": self.titles}

    @classmethod
    def from_dict(cls, data: dict) -> "TitlesCache":
        """从字典创建对象"""
        return cls(
            createTime=datetime.datetime.fromisoformat(data["createTime"]),
            titles=data.get("titles", []),
        )

    def save(self, filepath: str | Path) -> None:
        """保存到 JSON 文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)

    @classmethod
    def load(cls, filepath: str | Path) -> "TitlesCache":
        """从 JSON 文件加载"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def is_valid(self, max_age_days: int = 1) -> bool:
        """检查缓存是否有效"""
        if JUST_LOAD:
            return True
        return now_cst() - self.createTime < datetime.timedelta(days=max_age_days)

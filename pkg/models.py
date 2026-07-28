"""数据模型 — TitlesCache"""

import json
import datetime
from pathlib import Path
from dataclasses import dataclass

from config import JUST_LOAD


@dataclass
class TitlesCache:
    createTime: datetime.datetime
    titles: list[str]

    def to_dict(self) -> dict:
        """转换为字典用于 JSON 序列化"""
        return {
            "createTime": self.createTime.isoformat(),
            "titles": self.titles
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TitlesCache':
        """从字典创建对象"""
        return cls(
            createTime=datetime.datetime.fromisoformat(data["createTime"]),
            titles=data.get("titles", [])
        )

    def save(self, filepath: str | Path) -> None:
        """保存到 JSON 文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)

    @classmethod
    def load(cls, filepath: str | Path) -> 'TitlesCache':
        """从 JSON 文件加载"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def is_valid(self, max_age_days: int = 1) -> bool:
        """检查缓存是否有效"""
        if JUST_LOAD:
            return True
        return datetime.datetime.now() - self.createTime < datetime.timedelta(days=max_age_days)

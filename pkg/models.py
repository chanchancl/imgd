"""数据模型 — TitlesCache, CacheSnapshot, BatchRequest"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

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


# ============================================================
# Pydantic 请求模型（FastAPI 自动校验）
# ============================================================


class BatchRequestItem(BaseModel):
    type: str
    title: str = ""
    author: str = ""


class BatchRequest(BaseModel):
    requests: list[BatchRequestItem]


class MatchTitleRequest(BaseModel):
    title: str
    author: str = ""


class MatchAuthorRequest(BaseModel):
    author: str


class ExtractAuthorRequest(BaseModel):
    title: str


# ============================================================
# Pydantic 响应模型（response_model，自动生成 OpenAPI schema）
# ============================================================


class QueryResponse(BaseModel):
    """统一查询响应：各端点按需填写对应字段"""
    match: int
    title: str = ""
    author: str = ""


class RefreshCacheResponse(BaseModel):
    success: bool
    message: str


class TitlesResponse(BaseModel):
    titles: list[str]
    count: int


class AuthorsResponse(BaseModel):
    authors: list[str]
    count: int


class StatsResponse(BaseModel):
    cache_count: int
    author_count: int
    current_time: str
    request_stats: dict


class RootResponse(BaseModel):
    message: str


# ============================================================
# Tab 状态模型（chrome-tab-separator → dataserver）
# ============================================================


class TabOpenItem(BaseModel):
    """单个标签页打开/更新荷载"""
    tab_id: int
    title: str = ""
    url: str = ""
    window_id: int = 0


class TabOpenBatchRequest(BaseModel):
    """批量标签页打开/更新请求"""
    tabs: list[TabOpenItem]


class TabCloseBatchRequest(BaseModel):
    """批量标签页关闭请求"""
    tab_ids: list[int]


class TabsActionResponse(BaseModel):
    success: bool


class OpenTitlesResponse(BaseModel):
    titles: list[str]
    count: int

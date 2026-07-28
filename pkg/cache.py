"""缓存管理 — CacheStore、文件系统收集、trigram 索引构建"""

import os
import json
import asyncio
import datetime
import threading
from pathlib import Path

from config import SearchPathDir, JUST_LOAD
from autoclassfiy import FindArtistV2

from pkg.constants import (
    ENABLE_TRIGRAM_INDEX,
    CACHE_PATH,
    CACHE_REFRESH_INTERVAL_SECONDS,
    logger,
    searchPath,
)
from pkg.models import TitlesCache


# ============================================================
# n-gram 工具函数
# ============================================================

def _extract_ngrams(s: str, n: int = 3) -> set[str]:
    """提取字符串 s 中所有连续的 n 字符序列 (n-gram)。

    Args:
        s: 输入字符串
        n: n-gram 的长度，默认 3 trigram

    Returns:
        n-gram 集合；若 s 长度不足 n 则返回空集合
    """
    if len(s) < n:
        return set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


# ============================================================
# Trigram 索引构建
# ============================================================

def _build_trigram_index(titles: list[str]) -> dict[str, frozenset[int]]:
    """
        构建 trigram 索引：将每个 trigram 映射到包含它的标题索引集合。
        gram -> idx of title include gram
    """
    trigram_to_indices: dict[str, set[int]] = {}

    for idx, title in enumerate(titles):
        title_grams = _extract_ngrams(title)
        for gram in title_grams:
            if gram not in trigram_to_indices:
                trigram_to_indices[gram] = set()
            trigram_to_indices[gram].add(idx)

    # 冻结为不可变结构，允许无锁安全读取
    trigram_index = {g: frozenset(indices) for g, indices in trigram_to_indices.items()}
    return trigram_index


# ============================================================
# 文件系统收集
# ============================================================

def _collect_cleaned_titles_from_filesystem() -> list[str]:
    """从文件系统收集所有清理后的标题"""
    names_set = set()
    root_path = SearchPathDir

    if not os.path.exists(root_path):
        return []

    for _, dirs, files in os.walk(root_path):
        names_set.update(dirs)

        for filename in files:
            if filename.endswith(('.zip', '.rar')):
                names_set.add(os.path.splitext(filename)[0])

    # 从搜索路径收集
    for search_dir in searchPath:
        for entry in os.scandir(search_dir):
            if entry.is_file() and entry.name.endswith('.zip'):
                names_set.add(os.path.splitext(entry.name)[0])

    # 排序并返回列表（逆序）
    return sorted(names_set, reverse=True)


# ============================================================
# CacheStore
# ============================================================

class CacheStore:
    """
        线程安全的缓存状态管理器。
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.titles: list[str] = []
        self.authors: list[str] = []
        self.trigram_index: dict[str, frozenset[int]] = {}
        self.last_update_time = datetime.datetime.now()

    # ================================================================
    # 内部更新
    # ================================================================

    def _update(self, cleaned_titles: list[str]) -> None:
        if JUST_LOAD:
            existing = list(self.titles)
            merged = existing + cleaned_titles
        else:
            merged = cleaned_titles

        new_titles = [x.strip() for x in merged if not x.startswith("_")]
        new_titles = sorted(set(new_titles), reverse=True)

        if ENABLE_TRIGRAM_INDEX:
            new_trigram_index = _build_trigram_index(new_titles)
        else:
            new_trigram_index = {}

        new_authors: list[str] = []
        for title in new_titles:
            author = FindArtistV2(title).strip().lower()
            if author and author not in new_authors:
                new_authors.append(author)

        with self.lock:
            self.titles = new_titles
            self.trigram_index = new_trigram_index
            self.authors = new_authors

    # ================================================================
    # 加载 / 刷新
    # ================================================================

    async def refresh_loop(self) -> None:
        """后台循环：每隔 CACHE_REFRESH_INTERVAL_SECONDS 刷新一次缓存。"""
        while True:
            logger.info("Waiting for 12 hours to refresh cleaned title cache...")
            await asyncio.sleep(CACHE_REFRESH_INTERVAL_SECONDS)
            logger.info("Refresh cache every 12 hours")
            await self.load_or_create(create_cache=True)
            logger.info(f"Cleaned title cache refreshed, len: {len(self.titles)}")

    def load_from_file(self, cache_file_path: Path) -> bool:
        """尝试从 JSON 文件加载有效缓存。成功返回 True。"""
        if not cache_file_path.exists() or cache_file_path.stat().st_size <= 10:
            return False

        try:
            cache = TitlesCache.load(cache_file_path)
            if not cache.is_valid():
                logger.debug(f"Cache expired: {cache.createTime}")
                return False

            self._update(cache.titles)
            logger.debug(
                f"Loaded valid cache: {len(self.titles)} cleaned titles, "
                f"created at {cache.createTime}"
            )
            return True
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to load cache: {e}")
            return False

    async def load_or_create(self, create_cache: bool = False) -> TitlesCache | None:
        """加载或创建名称缓存。

        Args:
            create_cache: 是否强制重新创建缓存
        """
        cache_file_path = Path(CACHE_PATH)

        # 尝试加载现有缓存
        if not create_cache and self.load_from_file(cache_file_path) and not JUST_LOAD:
            return None

        # 从文件系统收集
        logger.debug("Collecting cleaned titles from filesystem...")
        cleaned_titles = _collect_cleaned_titles_from_filesystem()

        # 更新内部状态
        self._update(cleaned_titles)

        # 持久化到 JSON
        cache = TitlesCache(createTime=datetime.datetime.now(), titles=self.titles)
        cache.save(cache_file_path)

        logger.debug(
            f"Cache created/refreshed with {len(self.titles)} cleaned titles, "
            f"authorCache length: {len(self.authors)}"
        )
        return cache


# --- 模块级单例 ---
cache_store = CacheStore()

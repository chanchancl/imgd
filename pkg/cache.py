"""缓存管理 — CacheStore、文件系统收集、trigram 索引构建"""

import asyncio
import json
import os
import threading
from pathlib import Path

from autoclassfiy import FindArtistV2
from config import ManagedDir
from pkg.constants import (
    CACHE_PATH,
    CACHE_REFRESH_INTERVAL_SECONDS,
    ENABLE_TRIGRAM_INDEX,
    JUST_LOAD,
    extra_search_dirs,
    logger,
    now_cst,
)
from pkg.models import CacheSnapshot, TitlesCache

# ============================================================
# n-gram 工具函数
# ============================================================


def _extract_ngrams(s: str, n: int = 3) -> set[str]:
    """提取字符串 s 中所有连续 n-gram，长度不足则返回空集合"""
    if len(s) < n:
        return set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


# ============================================================
# n-gram 索引构建
# ============================================================


def _build_ngram_index(titles: list[str], n: int = 3) -> dict[str, frozenset[int]]:
    """构建 n-gram → frozenset[标题索引] 的倒排索引"""
    gram_to_indices: dict[str, set[int]] = {}

    for idx, title in enumerate(titles):
        title_grams = _extract_ngrams(title, n=n)
        for gram in title_grams:
            if gram not in gram_to_indices:
                gram_to_indices[gram] = set()
            gram_to_indices[gram].add(idx)

    # 冻结为不可变结构，允许无锁安全读取
    return {g: frozenset(indices) for g, indices in gram_to_indices.items()}


# ============================================================
# 文件系统收集
# ============================================================


def _collect_cleaned_titles_from_filesystem() -> list[str]:
    """从文件系统收集所有清理后的标题"""
    names_set = set()
    root_path = ManagedDir

    if os.path.exists(root_path):
        try:
            for _, dirs, files in os.walk(root_path):
                names_set.update(dirs)

                for filename in files:
                    if filename.endswith((".zip", ".rar")):
                        names_set.add(os.path.splitext(filename)[0])
        except OSError as e:
            logger.warning(f"Error walking ManagedDir '{root_path}': {e}")

    # 从搜索路径收集
    for search_dir in extra_search_dirs:
        if not os.path.isdir(search_dir):
            logger.warning(f"Extra search dir not found, skipping: {search_dir}")
            continue
        try:
            for entry in os.scandir(search_dir):
                if entry.is_file() and entry.name.endswith(".zip"):
                    names_set.add(os.path.splitext(entry.name)[0])
        except OSError as e:
            logger.warning(f"Error scanning search dir '{search_dir}': {e}")

    # 排序并返回列表（逆序）
    return sorted(names_set, reverse=True)


# ============================================================
# CacheStore
# ============================================================


class CacheStore:
    """线程安全的缓存状态管理器。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.titles: list[str] = []
        self.authors: list[str] = []
        self.author_set: set[str] = set()
        self.trigram_index: dict[str, frozenset[int]] = {}
        self.bigram_index: dict[str, frozenset[int]] = {}
        self.last_update_time = now_cst()
        self._snapshot = CacheSnapshot(
            titles=self.titles,
            trigram_index=self.trigram_index,
            bigram_index=self.bigram_index,
            authors=self.authors,
            author_set=self.author_set,
        )

    def get_snapshot(self) -> CacheSnapshot:
        """获取缓存一致性快照，无需加锁。"""
        return self._snapshot

    # ================================================================
    # 内部更新
    # ================================================================

    def _update(self, cleaned_titles: list[str]) -> None:
        with self.lock:
            # JUST_LOAD: 新收集的标题合并到已有缓存，而非替换
            if JUST_LOAD:
                existing = list(self.titles)
                merged = existing + cleaned_titles
            else:
                merged = cleaned_titles

        new_titles = [x.strip() for x in merged if not x.startswith("_")]
        # 去重 + 逆序排列（长的在前）
        new_titles = sorted(set(new_titles), reverse=True)

        if ENABLE_TRIGRAM_INDEX:
            new_trigram_index = _build_ngram_index(new_titles, n=3)
            new_bigram_index = _build_ngram_index(new_titles, n=2)
        else:
            new_trigram_index = {}
            new_bigram_index = {}

        new_authors: list[str] = []
        for title in new_titles:
            author = FindArtistV2(title).strip().lower()
            if author and author not in new_authors:
                new_authors.append(author)

        with self.lock:
            self.titles = new_titles
            self.trigram_index = new_trigram_index
            self.bigram_index = new_bigram_index
            self.authors = new_authors
            self.author_set = set(new_authors)
            # 原子替换快照，保证读取侧无需锁即可获取一致性视图
            self._snapshot = CacheSnapshot(
                titles=self.titles,
                trigram_index=self.trigram_index,
                bigram_index=self.bigram_index,
                authors=self.authors,
                author_set=self.author_set,
            )

    # ================================================================
    # 加载 / 刷新
    # ================================================================

    async def refresh_loop(self) -> None:
        """后台循环：每 CACHE_REFRESH_INTERVAL_SECONDS 刷新缓存"""
        while True:
            logger.info("Waiting for 12 hours to refresh cleaned title cache...")
            await asyncio.sleep(CACHE_REFRESH_INTERVAL_SECONDS)
            logger.info("Refresh cache every 12 hours")
            try:
                await self.load_or_create(create_cache=True)
                logger.info(f"Cleaned title cache refreshed, len: {len(self.titles)}")
            except Exception as e:  # noqa: BLE001 — 必须捕获所有异常防止循环退出
                logger.error(
                    f"Cache refresh loop failed, will retry in next cycle: {e}"
                )

    def load_from_file(self, cache_file_path: Path) -> bool:
        """从 JSON 文件加载有效缓存，成功返回 True"""
        # 文件不存在或内容极少（如空 JSON {}）则跳过
        try:
            if not cache_file_path.exists() or cache_file_path.stat().st_size <= 10:
                return False
        except OSError as e:
            logger.warning(f"Failed to stat cache file: {e}")
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
        except (
            json.JSONDecodeError,
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
        ) as e:
            logger.warning(f"Failed to load cache: {e}")
            return False

    async def load_or_create(self, create_cache: bool = False) -> TitlesCache | None:
        """加载或重新创建标题缓存"""
        cache_file_path = Path(CACHE_PATH)

        # 非强制刷新 + 已有有效缓存文件 + 非 JUST_LOAD → 直接用
        if not create_cache and self.load_from_file(cache_file_path) and not JUST_LOAD:
            return None

        # 从文件系统收集
        logger.debug("Collecting cleaned titles from filesystem...")
        cleaned_titles = _collect_cleaned_titles_from_filesystem()

        # 更新内部状态
        self._update(cleaned_titles)

        # 持久化到 JSON
        cache = TitlesCache(createTime=now_cst(), titles=self.titles)
        cache.save(cache_file_path)

        logger.debug(
            f"Cache created/refreshed with {len(self.titles)} cleaned titles, "
            f"authorCache length: {len(self.authors)}"
        )
        return cache


# --- 模块级单例 ---
cache_store = CacheStore()

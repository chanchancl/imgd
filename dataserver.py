import json
import math
import asyncio
import uvicorn
import difflib
import datetime
import os
import sys
import time
import threading
import socket
import signal
import pystray
import re

from pathlib import Path
from dataclasses import dataclass
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from cache_middleware import CacheMiddleware, MemoryBackend, cache as DCache
from cache_middleware.logger_config import logger as cm_logger

from utils import NewFileLogger
from config import SearchPathDir, DownloadPath, IgnoredNames, JUST_LOAD
from autoclassfiy import FindArtistV2
from PIL import Image, ImageDraw

"""
  Query 优化过程
  1. 尝试优化3个 match 函数本身
  2. 添加 batch 函数，将多个 query 合并为一个 http 请求
  3. 添加 trigram 索引，降低每次 query 的候选集大小
  4. 将 batch 改为异步并发处理，进一步降低总耗时,从 sum(O(N)) 改为 max(O(N))

  从原先完成一批request要耗时1-2s,优化到目前平均0.05s,最高不到0.1s,提速约 20-40倍
"""


# ============================================================
# 模块 1: 数据模型 — Data Models
# ============================================================

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
        # if JUST_LOAD:
        #     return
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


# ============================================================
# 模块 2: 配置与常量 — Configuration & Constants
# ============================================================

searchPath = [DownloadPath]

# Remove cache_middleware log
cm_logger.remove(0)

logger = NewFileLogger(__file__, True)

PART_MATCH_LENGTH_THRESHOLD = 10
PART_MATCH_THRESHOLD_DEFAULT = 0.65
PART_MATCH_THRESHOLD_SHORT = 0.85

FUZZY_MATCH_LENGTH_THRESHOLD = 15
FUZZY_MATCH_THRESHOLD_DEFAULT = 0.6
FUZZY_MATCH_THRESHOLD_SHORT = 0.8

CACHE_MIN_REFRESH_INTERVAL_HOURS = 1
CACHE_PATH = "cache/TitlesCache.json"
CACHE_REFRESH_INTERVAL_SECONDS = 3600 * 12  # 12 hours

DEBUG = False
ENABLE_TRIGRAM_INDEX = True

is_reload = True

# MatchStatus
MATCH_NO      = 0
MATCH_FUZZY   = 1
MATCH_PART    = 2
MATCH_EXACTLY = 3

_MATCH_TEXT = {
    MATCH_NO:      "MATCH_NO",
    MATCH_FUZZY:   "MATCH_FUZZY",
    MATCH_PART:    "MATCH_PART",
    MATCH_EXACTLY: "MATCH_EXACTLY",
}

def match_result_to_text(match_status: int) -> str:
    return _MATCH_TEXT.get(match_status, "ERROR")


# ============================================================
# 模块 3: 缓存管理 — Cache Management
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
        self.title_trigrams: list[frozenset[str]] = []
        self.last_update_time = datetime.datetime.now()

    # ================================================================
    # 内部更新
    # ================================================================

    def _update(self, cleaned_titles: list[str]) -> None:
        """用新的标题列表更新 titles / trigram_index / authors。

        所有 CPU 密集计算在锁外完成，仅最终赋值时短暂持锁。
        """
        # Phase 1: 构建新状态（无锁，纯本地计算）
        if JUST_LOAD:
            existing = list(self.titles)
            merged = existing + cleaned_titles
        else:
            merged = cleaned_titles

        new_titles = [x.strip() for x in merged if not x.startswith("_")]
        new_titles = sorted(set(new_titles), reverse=True)

        if ENABLE_TRIGRAM_INDEX:
            new_trigram_index, new_title_trigrams = _build_trigram_index(new_titles)
        else:
            new_trigram_index, new_title_trigrams = {}, []

        new_authors: list[str] = []
        for title in new_titles:
            author = FindArtistV2(title).strip().lower()
            if author and author not in new_authors:
                new_authors.append(author)

        # Phase 2: 原子替换（短暂持锁）
        with self.lock:
            self.titles = new_titles
            self.trigram_index = new_trigram_index
            self.title_trigrams = new_title_trigrams
            self.authors = new_authors

    # ================================================================
    # 加载 / 刷新
    # ================================================================

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

    async def refresh_loop(self) -> None:
        """后台循环：每隔 CACHE_REFRESH_INTERVAL_SECONDS 刷新一次缓存。"""
        while True:
            logger.info("Waiting for 12 hours to refresh cleaned title cache...")
            await asyncio.sleep(CACHE_REFRESH_INTERVAL_SECONDS)
            logger.info("Refresh cache every 12 hours")
            await self.load_or_create(create_cache=True)
            logger.info(f"Cleaned title cache refreshed, len: {len(self.titles)}")


# --- 模块级纯函数（不访问 CacheStore 状态）---

def _collect_cleaned_titles_from_filesystem() -> list[str]:
    """从文件系统收集所有清理后的标题"""
    names_set = set()
    root_path = SearchPathDir

    if os.path.exists(root_path):
        for root, dirs, files in os.walk(root_path):
            # 跳过根目录本身
            if root == root_path:
                names_set.update(dirs)
                continue

            names_set.update(dirs)

            # 处理文件
            for filename in files:
                if filename.endswith(('.zip', '.rar')):
                    # 获取不带扩展名的文件名
                    stem = os.path.splitext(filename)[0]
                    names_set.add(stem)

    # 从搜索路径收集
    for search_dir in searchPath:
        for entry in os.scandir(search_dir):
            if entry.is_file() and entry.name.endswith('.zip'):
                stem = os.path.splitext(entry.name)[0]
                names_set.add(stem)

    # 排序并返回列表（逆序）
    return sorted(names_set, reverse=True)


def _build_trigram_index(titles: list[str]) -> tuple[dict[str, frozenset[int]], list[frozenset[str]]]:
    """从标题列表中构建 trigram 索引。

    为每个标题提取所有连续的 3 字符序列(trigram),
    构建从 trigram 到包含该 trigram 的标题索引集合的映射。

    Args:
        titles: 去重排序后的标题列表

    Returns:
        (trigram_index, title_trigrams) 的元组:
        - trigram_index: trigram → 包含该 trigram 的标题索引的 frozenset
        - title_trigrams: 每个标题所包含的 trigram 的 frozenset 列表
    """
    trigram_to_indices: dict[str, set[int]] = {}
    per_title: list[set[str]] = []

    for idx, title in enumerate(titles):
        title_grams = _extract_ngrams(title)
        for gram in title_grams:
            if gram not in trigram_to_indices:
                trigram_to_indices[gram] = set()
            trigram_to_indices[gram].add(idx)
        per_title.append(title_grams)

    # 冻结为不可变结构，允许无锁安全读取
    trigram_index = {g: frozenset(indices) for g, indices in trigram_to_indices.items()}
    title_trigrams = [frozenset(s) for s in per_title]
    return trigram_index, title_trigrams


# --- 模块级单例 ---
cache_store = CacheStore()


# ============================================================
# 模块 4: 匹配引擎 — Matching Engine
# ============================================================

# 数字范围分隔符归一化表：将所有变体统一映射到 '-'
_RANGE_SEP_TRANS = str.maketrans({
    '～': '-',  # ～ fullwidth tilde
    '〜': '-',  # 〜 wave dash (日文)
    '－': '-',  # － fullwidth hyphen-minus
    '~': '-',  # ~ ascii tilde
})


def _normalize_range_separators(s: str) -> str:
    """将各种数字范围分隔符统一转换为 '-'，确保缓存和输入一致匹配。"""
    return s.translate(_RANGE_SEP_TRANS)


def check_author_in_title(title: str, author: str):
    return author == "" or author in title


def extract_number_from_string(s: str) -> int | None:
    """从字符串中提取卷号/数字。

    优先匹配卷号模式（v01, Vol.1, #01），
    其次尝试最后一个空格分隔的含数字 token，
    最后尝试任意位置的数字。
    """
    # 优先：卷号模式 v01 / Vol.1 / #01
    m = re.search(r'(?i)\b(?:v|vol\.?\s*)(\d+)', s)
    if m:
        return int(m.group(1))
    m = re.search(r'#(\d+)', s)
    if m:
        return int(m.group(1))

    # 其次：从右向左找空格分隔的含数字 token
    parts = s.split(' ')
    for p in reversed(parts):
        m = re.search(r'\d+', p)
        if m:
            return int(m.group())

    # 兜底：字符串中任意数字
    m = re.search(r'\d+', s)
    return int(m.group()) if m else None


def extract_number_range_from_string(s: str) -> tuple[int, int] | None:
    """从字符串中提取数字范围（如 1-3, 01~05, 1～3）。

    先归一化所有分隔符变体为 '-'，再匹配。过滤日期和序数词。
    """
    s = _normalize_range_separators(s)

    for m in re.finditer(r'(\d+)\s*-\s*(\d+)', s):
        start = int(m.group(1))
        end = int(m.group(2))
        if start > end:
            continue

        # 过滤：日期格式（年份 1900-2100）
        if 1900 <= start <= 2100:
            continue

        # 过滤：序数词（1st, 2nd, 21th 等）
        after = s[m.end():m.end() + 3].lower()
        if re.match(r'(st|nd|rd|th)', after):
            continue

        return start, end

    return None


def exactly_match(cached_title: str, input_title: str) -> tuple[bool, str]:
    if not cached_title or not input_title:
        return False, ""

    # 归一化：统一分隔符，让 1-3 / 1~3 / 1～3 等价
    nc = _normalize_range_separators(cached_title)
    ni = _normalize_range_separators(input_title)

    if ni in nc:
        return True, cached_title

    range_match = extract_number_range_from_string(nc)
    if not range_match:
        return False, ""

    range_start, range_end = range_match
    query_number = extract_number_from_string(ni)
    if query_number is None or query_number < range_start or query_number > range_end:
        return False, ""

    query_without_number = ni.replace(str(query_number), "")
    if query_without_number and query_without_number in nc:
        return True, cached_title

    return False, ""


def part_match(cached_title: str, input_title: str) -> tuple[bool, str]:
    if not input_title or not cached_title:
        return False, ""

    threshold = PART_MATCH_THRESHOLD_DEFAULT
    if len(input_title) < PART_MATCH_LENGTH_THRESHOLD:
        threshold = PART_MATCH_THRESHOLD_SHORT

    min_len = math.ceil(len(input_title) * threshold)

    match = difflib.SequenceMatcher(None, input_title, cached_title).find_longest_match()
    if match.size >= min_len:
        return True, input_title[match.a:match.a + match.size]

    return False, ""


def fuzz_match(cached_titles: list[str], input_title: str, input_author: str) -> tuple[bool, str]:
    threshold = FUZZY_MATCH_THRESHOLD_DEFAULT
    if len(input_title) < FUZZY_MATCH_LENGTH_THRESHOLD:
        threshold = FUZZY_MATCH_THRESHOLD_SHORT
    matches = difflib.get_close_matches(input_title, cached_titles, n=3, cutoff=threshold)
    for fuzzy_match in matches:
        if not check_author_in_title(fuzzy_match, input_author):
            continue
        return True, fuzzy_match
    return False, ""


# ============================================================
# 模块 5: Trigram 索引候选过滤 — Trigram Candidate Filtering
# ============================================================

def _extract_ngrams(s: str, n: int = 3) -> set[str]:
    """提取字符串 s 中所有连续的 n 字符序列 (n-gram)。

    Args:
        s: 输入字符串
        n: n-gram 的长度，默认 3（trigram）

    Returns:
        n-gram 集合；若 s 长度不足 n 则返回空集合
    """
    if len(s) < n:
        return set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _exact_candidates(input_title: str) -> list[int]:
    """返回包含 input_title 全部 trigram 的标题索引列表。

    这是子字符串匹配的必要条件：如果 input_title 是某个 cached_title
    的子字符串，那么 input_title 的所有 trigram 必须都出现在该 cached_title 中。
    若输入长度不足 3 个字符，则回退到全量扫描。

    Args:
        input_title: 输入的查询标题

    Returns:
        候选标题索引列表；若无法匹配任何 trigram 则返回空列表
    """
    if not ENABLE_TRIGRAM_INDEX or len(input_title) < 3:
        return list(range(len(cache_store.titles)))

    # 提取输入的所有 trigram
    input_grams = _extract_ngrams(input_title)

    if not input_grams:
        return list(range(len(cache_store.titles)))

    # 对所有 trigram 的索引集合取交集，最后排序以保证确定性的匹配顺序
    it = iter(input_grams)
    first = next(it)
    result_set = cache_store.trigram_index.get(first)
    if result_set is None:
        return []  # 第一个 trigram 就不在任何标题中

    result = set(result_set)  # 转换为可变 set 以便迭代交集
    for gram in it:
        s = cache_store.trigram_index.get(gram)
        if s is None:
            return []  # 某个 trigram 不在任何标题中，不可能有匹配
        result &= s
        if not result:
            return []

    return sorted(result)  # 排序以保持与全量扫描一致的顺序


def _fuzzy_candidates(input_title: str) -> list[int]:
    """返回包含 input_title 任一 trigram 的标题索引列表。

    对于部分匹配和模糊匹配，有效的匹配必须共享至少一个 trigram。
    若候选数量超过缓存总量的一半，则回退到全量扫描以避免过滤开销浪费。
    若输入长度不足 3 个字符，则回退到全量扫描。

    Args:
        input_title: 输入的查询标题

    Returns:
        候选标题索引列表
    """
    if not ENABLE_TRIGRAM_INDEX or len(input_title) < 3:
        return list(range(len(cache_store.titles)))

    half = len(cache_store.titles) // 2
    candidates: set[int] = set()
    for gram in _extract_ngrams(input_title):
        s = cache_store.trigram_index.get(gram)
        if s:
            candidates.update(s)
            if len(candidates) > half:
                # 候选太多，过滤收益不大，直接全量扫描
                return list(range(len(cache_store.titles)))

    if not candidates:
        # 没有任何 trigram 匹配，但为防误判仍需全量扫描
        # return list(range(len(cache_store.titles)))
        return []

    return sorted(candidates)  # 排序以保持与全量扫描一致的顺序


# ============================================================
# 模块 6: 查询服务 — Query Service
# ============================================================

async def query_match_title(input_title: str, input_author: str = "") -> tuple[int, str]:
    if input_title == "":
        return MATCH_NO, ""

    # 在锁内复制缓存列表，保证一致性
    with cache_store.lock:
        cached_titles = cache_store.titles.copy()

    match_status = MATCH_NO
    matched_title = "<empty>"

    # EXACTLY MATCH, input_title 是某个 cached_title 的子字符串
    # 使用 trigram 交集过滤：候选标题必须包含 input_title 的全部 trigram
    for idx in _exact_candidates(input_title):
        cached_title = cached_titles[idx]
        ok, matched = exactly_match(cached_title, input_title)
        if ok and check_author_in_title(cached_title, input_author):
            match_status = MATCH_EXACTLY
            matched_title = cached_title
            break

    # PART MATCH, input_title 与 cached_title 有足够长的公共子串
    # 使用 trigram 并集过滤：候选标题只需包含 input_title 的任一 trigram
    if not match_status:
        for idx in _fuzzy_candidates(input_title):
            cached_title = cached_titles[idx]
            ok, matched = part_match(cached_title, input_title)
            if ok and check_author_in_title(cached_title, input_author):
                match_status = MATCH_PART
                matched_title = cached_title
                logger.debug(f"PART MATCH : {matched} in {cached_title}")
                break

    # FUZZY MATCH, 使用 difflib.get_close_matches 进行模糊匹配
    # 同样使用 trigram 并集过滤，仅在候选子集上运行昂贵的模糊匹配
    if not match_status:
        candidate_indices = _fuzzy_candidates(input_title)
        candidate_titles = [cached_titles[i] for i in candidate_indices]
        ok, matched = fuzz_match(candidate_titles, input_title, input_author)
        if ok and check_author_in_title(cached_title, input_author):
            match_status = MATCH_FUZZY
            matched_title = matched

    # logger.debug(f"Match Result : {match_result_to_text(match_status)}, {matched_title}")

    return match_status, matched_title


async def query_author(author: str):
    if author == "":
        return MATCH_NO
    lower_author = author.lower()
    for cached_author in cache_store.authors:
        if lower_author == cached_author:
            return MATCH_EXACTLY
    for cached_author in cache_store.authors:
        if lower_author in cached_author:
            return MATCH_PART
    return MATCH_NO


# ============================================================
# FastAPI Server & API 路由
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # start
    logger.debug(f"Reload mode : {is_reload}")
    await cache_store.load_or_create()
    asyncio.create_task(cache_store.refresh_loop())

    # running
    # handle request
    yield
    # exit


app = FastAPI(lifespan=lifespan)

memory_backend = MemoryBackend(max_size=1000)
if not DEBUG:
    app.add_middleware(CacheMiddleware, backend=memory_backend)


# Allow CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=86400,
)


@app.middleware('http')
async def updateCacheMiddleware(req: Request, call_next):
    current_time = datetime.datetime.now()
    elapsed_time = current_time - cache_store.last_update_time
    refresh_interval = datetime.timedelta(hours=CACHE_MIN_REFRESH_INTERVAL_HOURS)
    if elapsed_time > refresh_interval:
        cache_store.last_update_time = current_time
        logger.debug(f"Refresh cache due to {CACHE_MIN_REFRESH_INTERVAL_HOURS} hour passed since last query")
        await cache_store.load_or_create(create_cache=True)
        memory_backend.close()

    return await call_next(req)


# 统计 request 用时
@app.middleware('http')
async def timeCostMiddleware(req: Request, call_next):
    start = datetime.datetime.now()
    rsp = await call_next(req)
    eplased = datetime.datetime.now() - start
    logger.debug(f"Query use {eplased}")
    return rsp


@app.get("/")
@DCache(timeout=300)
async def _():
    return JSONResponse(content={"message": f"Hello, World! Cache created/refreshed with {len(cache_store.titles)} cleaned titles, "
        f"authorCache length: {len(cache_store.authors)}"})

def make_response(match_status: int, match_title: str):
    return JSONResponse(content={"title": match_title, "match": match_status})

@app.post("/query/match-title")
@DCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    in_author = data.get('author')
    in_title: str = data.get("title")
    if not in_title:
        logger.debug("Query Title, no valid title found")
        return make_response(MATCH_NO, "")

    in_title = in_title.replace("?", "_")  # ? is invalid character in windows path

    for ignoreKeyword in IgnoredNames:
        if ignoreKeyword in in_title:
            return make_response(MATCH_NO, "")

    match_status, matched_title = await query_match_title(in_title, in_author)
    if match_status:
        logger.debug(f"Query Title, Found '{in_title}' and author '{in_author}', ")
        return make_response(match_status, matched_title)

    logger.debug(f"Query Title, Not Found '{in_title}' and author '{in_author}'")
    return make_response(match_status, "")


async def _process_batch_request(req: dict) -> dict:
    """处理单个 batch 请求，支持并发调用。"""
    req_type = req.get("type", "")

    if req_type == "extract-author":
        title: str = req.get("title", "")
        # FindArtistV2 是同步函数，放入线程池避免阻塞事件循环
        author = FindArtistV2(title)
        match_status = MATCH_NO if author == "" else MATCH_EXACTLY
        return {"type": req_type, "author": author, "match": match_status}

    elif req_type == "match-author":
        author: str = req.get("author", "")
        match_status = await query_author(author)
        return {"type": req_type, "match": match_status}

    elif req_type == "match-title":
        in_author = req.get("author", "")
        in_title: str = req.get("title", "")
        if not in_title:
            return {"type": req_type, "title": "", "match": MATCH_NO}

        in_title = in_title.replace("?", "_")

        for ignoreKeyword in IgnoredNames:
            if ignoreKeyword in in_title:
                return {"type": req_type, "title": "", "match": MATCH_NO}

        match_status, matched_title = await query_match_title(in_title, in_author)
        return {
            "type": req_type,
            "title": matched_title if match_status else "",
            "match": match_status
        }

    elif req_type == "extract-match-author-and-match-title":
        # 理论上这才是新加的API，上面三个都仅仅是旧API的 BATCH 版本
        # extract-verify-author + match-title
        in_author = req.get("author", "").strip()
        in_title: str = req.get("title", "").strip()

        # author 查询（允许空字符串，返回 MATCH_NO）
        out_author = FindArtistV2(in_title)
        out_author = out_author if out_author else in_author
        author_match = await query_author(out_author) if in_author else MATCH_NO

        # title 查询（复用 match-title 的过滤逻辑）
        if not in_title:
            title_match = MATCH_NO
        else:
            in_title = in_title.replace("?", "_")
            ignored = any(keyword in in_title for keyword in IgnoredNames)
            if ignored:
                title_match = MATCH_NO
            else:
                title_match, _ = await query_match_title(in_title, in_author)

        return {
            "type": req_type,
            "author": out_author,
            "author_match": author_match,
            "title_match": title_match,
        }

    else:
        return {"type": req_type, "error": f"Unknown request type: {req_type}"}


# 单次http请求处理大量的request
@app.post("/query/batch")
@DCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    requests_list: list[dict] = data.get("requests")

    if not requests_list:
        return JSONResponse(
            content={"error": "Missing or empty 'requests' field"},
            status_code=422
        )

    # 并发处理所有请求，保持输入顺序
    tasks = [_process_batch_request(req) for req in requests_list]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for i, result in enumerate(gathered):
        if isinstance(result, Exception):
            logger.error(
                f"Batch request error for '{requests_list[i].get('type', '')}': {result}"
            )
            results.append({
                "type": requests_list[i].get("type", ""),
                "error": str(result)
            })
        else:
            results.append(result)

    return JSONResponse(content={"results": results})


@app.post("/query/match-author")
@DCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    author = data.get("author")

    match_status = await query_author(author)
    if match_status:
        logger.debug(f"Query Author, Found '{author}'")
        return JSONResponse(content={"match": match_status})

    logger.debug(f"Query Author, Not Found : '{author}'")
    return JSONResponse(content={"match": match_status})


@app.post("/query/extract-author")
@DCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    title = data.get("title")
    author = FindArtistV2(title)
    match_status = MATCH_NO if author == "" else MATCH_EXACTLY
    logger.debug(f"Find artist for {title} : {author}")
    return JSONResponse(content={"author": author, "match": match_status})


@app.post("/refresh-cache")
async def refresh_cache_endpoint():
    """手动刷新缓存"""
    try:
        await cache_store.load_or_create(create_cache=True)
        # 更新菜单显示（如果托盘图标存在）
        # 这里可以触发菜单更新，但需要访问icon对象
        return JSONResponse(content={"success": True, "message": "Cache refreshed successfully"})
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Failed to refresh cache: {e}")
        return JSONResponse(content={"success": False, "message": f"Cache refresh failed: {e}"}, status_code=500)


@app.get("/api/titles")
@DCache(timeout=300)
async def get_titles_list():
    """获取所有清理后的标题列表"""
    return JSONResponse(content={
        "titles": cache_store.titles,
        "count": len(cache_store.titles)
    })


@app.get("/api/authors")
@DCache(timeout=300)
async def get_authors_list():
    """获取所有作者列表"""
    return JSONResponse(content={
        "authors": cache_store.authors,
        "count": len(cache_store.authors)
    })


@app.get("/api/stats")
@DCache(timeout=300)
async def get_stats():
    """获取缓存统计信息"""
    return JSONResponse(content={
        "cache_count": len(cache_store.titles),
        "author_count": len(cache_store.authors),
        "current_time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.get("/admin")
@DCache(timeout=300)
async def admin_dashboard():
    """管理仪表板页面"""
    cache_count = len(cache_store.titles)
    author_count = len(cache_store.authors)
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 读取HTML模板文件
    template_path = Path(__file__).parent / "templates/admin.html"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 替换模板变量
        html_content = html_content.replace("{cache_count}", str(cache_count))
        html_content = html_content.replace("{author_count}", str(author_count))
        html_content = html_content.replace("{current_time}", current_time)

        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        logger.error(f"Template file not found: {template_path}")
        # 返回一个简单的错误页面
        return HTMLResponse(content=f"""
            <html><body>
                <h1>Error: Template file not found</h1>
                <p>Please create templates/admin.html</p>
                <p>Cache stats: {cache_count} titles, {author_count} authors</p>
            </body></html>
        """, status_code=500)


# ============================================================
# 模块 7: 服务器生命周期管理 — Server Lifecycle
# ============================================================

class ServerRunner:
    """管理 FastAPI 服务器 + 系统托盘 + 事件循环的完整生命周期。

    将原来分散的 myloop、uvicorn_server 全局变量以及托盘函数、
    启动流程收拢为一个类，消除 global 声明，使启动/停止逻辑内聚。
    """

    def __init__(self, app: FastAPI, host: str = "127.0.0.1", port: int = 8353):
        self.app = app
        self.host = host
        self.port = port
        self.loop = asyncio.new_event_loop()
        self.uvicorn_server: uvicorn.Server | None = None

    # ================================================================
    # 事件循环 / uvicorn
    # ================================================================

    def run_uvicorn(self) -> None:
        """在 self.loop 中运行 uvicorn 服务器（阻塞当前线程）。"""
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port,
            log_level="info", reload=True
        )
        self.uvicorn_server = uvicorn.Server(config)
        self.loop.run_until_complete(self.uvicorn_server.serve())

    def start_loop_in_background(self) -> None:
        """在后台线程中启动 self.loop，用于托盘图标回调。"""
        if not self.loop.is_running():
            def run_loop():
                self.loop.run_forever()
            loop_thread = threading.Thread(target=run_loop, daemon=True)
            loop_thread.start()
            logger.debug("Started event loop in background thread for tray callbacks")

    # ================================================================
    # 托盘图标
    # ================================================================

    @staticmethod
    def _create_tray_image() -> Image.Image:
        """创建一个简单的托盘图标（绿色背景 + 白字 S）。"""
        image = Image.new('RGB', (64, 64), color=(0, 100, 0))
        dc: ImageDraw.ImageDraw = ImageDraw.Draw(image)
        dc.text((32, 32), "S", fill=(255, 255, 255), font_size=48, anchor="mm")
        return image

    def _on_open_browser(self, icon, item) -> None:
        import webbrowser
        webbrowser.open(f"http://{self.host}:{self.port}/admin")

    def _on_refresh_cache(self, icon, item) -> None:
        future = asyncio.run_coroutine_threadsafe(
            cache_store.load_or_create(create_cache=True), self.loop
        )

        def on_cache_refreshed(f):
            try:
                f.result()
                icon.update_menu()
            except (asyncio.CancelledError, RuntimeError) as e:
                logger.warning(f"Cache refresh callback error: {e}")
        future.add_done_callback(on_cache_refreshed)

    def _on_exit(self, icon, item) -> None:
        icon.stop()
        if is_reload:
            parent_pid = os.getppid()
            os.kill(parent_pid, signal.SIGTERM)
        self_pid = os.getpid()
        os.kill(self_pid, signal.SIGTERM)

    def _setup_tray(self) -> None:
        image = self._create_tray_image()

        def make_menu():
            return pystray.Menu(
                pystray.MenuItem(
                    f"打开管理页面 (localhost:{self.port}/admin)",
                    self._on_open_browser
                ),
                pystray.MenuItem(
                    lambda text: f"立即刷新缓存 ({len(cache_store.titles)})",
                    self._on_refresh_cache
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self._on_exit)
            )

        icon = pystray.Icon("dataserver", image, f"server ({self.port})", make_menu())
        icon.run()

    def start_tray_in_thread(self) -> threading.Thread:
        """在后台线程中启动托盘图标。"""
        tray_thread = threading.Thread(target=self._setup_tray, daemon=True)
        tray_thread.start()
        return tray_thread

    # ================================================================
    # 启动入口
    # ================================================================

    def start(self, with_tray: bool = False) -> None:
        """按模式启动服务器。

        Args:
            with_tray: 是否同时启动系统托盘图标（uvicorn reload 模式）
        """
        if with_tray:
            logger.debug("Starting tray icon due to uvicorn reload mode")
            self.start_loop_in_background()
            self.start_tray_in_thread()


# --- 模块级工具函数 ---

def check_singleton(port: int = 8353) -> bool:
    """检查端口是否已被占用（防止重复启动）。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        if result == 0:
            print("⚠️  Server already running on port 8353")
            print("   Another instance of dataserver is already running.")
            print("   Exiting this instance.")
            return True
    except (socket.error, TimeoutError, OSError) as e:
        print(f"⚠️  Port check error: {e}")
        return False
        # 继续运行，不因检测错误而退出


# --- 模块级单例 ---
runner = ServerRunner(app, host="127.0.0.1", port=8353)


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    # run by python dataserver.py
    if check_singleton():
        sys.exit(0)

    is_reload = False

    # 启动 FastAPI 服务（在线程中）
    uvicorn_thread = threading.Thread(target=runner.run_uvicorn, daemon=True)
    uvicorn_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        sys.exit(0)
else:
    # run by uvicorn
    runner.start(with_tray=True)

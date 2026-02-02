import json
import math
import asyncio
import uvicorn
import difflib
import datetime

from pathlib import Path
from dataclasses import dataclass
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from cache_middleware import CacheMiddleware, MemoryBackend, cache as DecoratorCache
from cache_middleware.logger_config import logger as cm_logger

from utils import NewFileLogger
from infos import DownloadDir, ActualDownload, IgnoredNames
from autoclassfiy import FindArtistV2


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
        return datetime.datetime.now() - self.createTime < datetime.timedelta(days=max_age_days)

searchPath = [ActualDownload]

cm_logger.remove(0)

logger = NewFileLogger(__file__, True)

# FoundResult
# 1.Exactly match
# 2.Part match
# 3.Fuzzy match
# 4.No match
#
MATCH_NO      = 0
MATCH_FUZZY   = 1
MATCH_PART    = 2
MATCH_EXACTLY = 3

PART_MATCH_THRESHOLD = 0.65
CACHE_MIN_REFRESH_INTERVAL_HOURS = 1
CACHE_PATH = "cache/TitlesCache.json"

last_cache_update_time = datetime.datetime.now()
cleaned_title_cache_list = []
author_cache_list = []



def _collect_cleaned_titles_from_filesystem() -> list[str]:
    """从文件系统收集所有清理后的标题"""
    names = []
    root = Path(DownloadDir)

    if root.exists():
        for path, dirnames, filenames in root.walk():
            if path == root:
                continue
            names.extend(dirnames)
            names.extend(
                Path(filename).stem
                for filename in filenames
                if filename.endswith(('.zip', '.rar'))
            )

    # 从搜索路径收集
    names.extend(
        p.stem
        for search_dir in searchPath
        for p in Path(search_dir).iterdir()
        if p.is_file() and p.suffix == '.zip'
    )

    return sorted(set(names), reverse=True)  # 去重并排序


def _update_global_cache(cleaned_titles: list[str]) -> None:
    """更新全局缓存列表"""
    cleaned_title_cache_list.clear()
    cleaned_title_cache_list.extend(cleaned_titles)
    get_author_from_cleaned_title_cache()


def _try_load_valid_cache(cache_file_path: Path) -> bool:
    """
    尝试加载有效的缓存

    Returns:
        缓存是否成功加载
    """
    if not cache_file_path.exists() or cache_file_path.stat().st_size <= 10:
        return False

    try:
        cache = TitlesCache.load(cache_file_path)
        if not cache.is_valid():
            logger.debug(f"Cache expired: {cache.createTime}")
            return False

        _update_global_cache(cache.titles)
        logger.debug(
            f"Loaded valid cache: {len(cleaned_title_cache_list)} cleaned titles, "
            f"created at {cache.createTime}"
        )
        return True
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Failed to load cache: {e}")
        return False


async def load_or_create_cache(create_cache: bool = False) -> TitlesCache:
    """
    加载或创建名称缓存

    Args:
        createCache: 是否强制重新创建缓存

    Returns:
        NameCache 对象
    """
    cache_file_path = Path(CACHE_PATH)

    # 尝试加载现有缓存
    if not create_cache and _try_load_valid_cache(cache_file_path):
        return

    # 收集文件系统中的清理后的标题
    logger.debug("Collecting cleaned titles from filesystem...")
    cleaned_titles = _collect_cleaned_titles_from_filesystem()

    # 创建并保存新缓存
    cache = TitlesCache(createTime=datetime.datetime.now(), titles=cleaned_titles)
    cache.save(cache_file_path)

    # 更新全局缓存
    _update_global_cache(cleaned_titles)

    logger.debug(
        f"Cache created/refreshed with {len(cleaned_title_cache_list)} cleaned titles, "
        f"authorCache length: {len(author_cache_list)}"
    )
    return cache


def check_author_in_title(title: str, author: str):
    return author == "" or author in title


def part_match(cached_title: str, cleaned_title: str):
    match_type = MATCH_NO
    limit = int(math.ceil(len(cleaned_title) * (1 - PART_MATCH_THRESHOLD)))
    # found half of the title
    for trim_length in range(1, min(20, limit)):
        title_prefix = cleaned_title[:-trim_length]
        if title_prefix == "":
            break
        if title_prefix in cached_title:
            match_type = MATCH_PART
            break
    return match_type


def get_author_from_cleaned_title_cache():
    author_cache_list.clear()
    for cleaned_title in cleaned_title_cache_list:
        author = FindArtistV2(cleaned_title)
        if len(author) == 0 or author in author_cache_list:
            continue
        author_cache_list.append(author)


async def query_cleaned_title(cleaned_title: str, author: str = "") -> tuple[int, str]:
    if cleaned_title == "":
        return MATCH_NO, ""

    match_type = MATCH_NO
    matched_title = ""

    # EXACTLY MATCH, title in cached_title
    for cached_title in cleaned_title_cache_list:
        # if title in cached_title, 视为EXACTLY，和author判断不太一样
        if cleaned_title in cached_title:
            print(f"found {cleaned_title}")
            if check_author_in_title(cached_title, author):
                match_type = MATCH_EXACTLY
                matched_title = cached_title
                logger.debug(f"Match Result : {match_type}, {matched_title}")
                return match_type, matched_title

    # PART MATCH, part of title in cached_title
    for cached_title in cleaned_title_cache_list:
        if part_match(cached_title, cleaned_title):
            match_type = MATCH_PART
            matched_title = cached_title
            logger.debug(f"Match Result : {match_type}, {matched_title}")
            return match_type, matched_title

    # FUZZY MATCH, title is fuzzy matched with one of cleaned_title_cache_list
    fuzzy_match_threshold = 0.6
    if len(cleaned_title) < 15:
        fuzzy_match_threshold = 0.8
    matches = difflib.get_close_matches(cleaned_title, cleaned_title_cache_list, n=3, cutoff=fuzzy_match_threshold)
    for fuzzy_match in matches:
        if not check_author_in_title(fuzzy_match, author):
            logger.debug(f"fuzzy match : {fuzzy_match}, but author not found : {author}")
            continue
        logger.debug(f"Query Title {cleaned_title}, fuzzy match found {fuzzy_match}")
        match_type = MATCH_FUZZY
        matched_title = fuzzy_match
        break
    logger.debug(f"Match Result : {match_type}, {matched_title}")
    return match_type, matched_title


async def query_author(author: str):
    for cached_author in author_cache_list:
        if author == cached_author:
            return MATCH_EXACTLY
    for cached_author in author_cache_list:
        if author in cached_author:
            return MATCH_PART
    return MATCH_NO


async def refresh_cleaned_title_cache():
    global cleaned_title_cache_list
    while True:
        logger.info("Waiting for 12 hours to refresh cleaned title cache...")
        await asyncio.sleep(3600 * 12)  # Refresh every 12 hours
        cleaned_title_cache_list = []
        logger.info("Refresh cache every 12 hours")
        await load_or_create_cache(create_cache=True)
        logger.info(f"Cleaned title cache refreshed, len: {len(cleaned_title_cache_list)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # start
    await load_or_create_cache()
    asyncio.create_task(refresh_cleaned_title_cache())
    # handle request
    yield
    # exit


app = FastAPI(lifespan=lifespan)

memory_backend = MemoryBackend(max_size=1000)
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
    global last_cache_update_time
    current_time = datetime.datetime.now()
    elapsed_time = current_time - last_cache_update_time
    refresh_interval = datetime.timedelta(hours=CACHE_MIN_REFRESH_INTERVAL_HOURS)
    if elapsed_time > refresh_interval:
        last_cache_update_time = current_time
        logger.debug(f"Refresh cache due to {CACHE_MIN_REFRESH_INTERVAL_HOURS} hour passed since last query")
        await load_or_create_cache(create_cache=True)
        memory_backend.close()
    return await call_next(req)


# @app.middleware('http')
# async def timeCostMiddleware(req: Request, call_next):
#     start = datetime.datetime.now()
#     rsp = await call_next(req)
#     eplased = datetime.datetime.now() - start
#     logger.debug(f"Query use {eplased}")
#     return rsp


@app.get("/")
@DecoratorCache(timeout=300)
async def _():
    return JSONResponse(content={"message": "Hello, World!"})


@app.post("/query/cleaned-title")
@DecoratorCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    author = data.get('author')
    cleaned_title: str = data.get("name")
    cleaned_title = cleaned_title.replace("?", "_")  # ? is invalid character in windows path

    for ignore in IgnoredNames:
        if ignore in cleaned_title:
            return JSONResponse(content={"name": "", "match": MATCH_NO})

    match_type, matched_title = await query_cleaned_title(cleaned_title, author)
    if match_type:
        logger.debug(f"Found title '{cleaned_title}' and author '{author}', ")
        return JSONResponse(content={"name": matched_title, "match": match_type})

    logger.debug(f"Nothing found '{cleaned_title}' and author '{author}'")
    return JSONResponse(content={"name": "", "match": match_type})


@app.post("/query/author")
@DecoratorCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    author = data.get("author")

    match_type = await query_author(author)
    if match_type:
        logger.debug(f"Found author '{author}'")
        return JSONResponse(content={"match": match_type})

    logger.debug(f"Nothing found, author : '{author}'")
    return JSONResponse(content={"match": match_type})


@app.post("/query/extract-author")
@DecoratorCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    title = data.get("title")
    author = FindArtistV2(title)
    match_type = MATCH_NO if author == "" else MATCH_EXACTLY
    logger.debug(f"Find artist for {title} : {author}")
    return JSONResponse(content={"author": author, "match": match_type})

if __name__ == "__main__":
    # 只在直接运行时启动 uvicorn
    uvicorn.run(app, host="localhost", port=8000, log_level="info")

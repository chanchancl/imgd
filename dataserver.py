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

searchPath = [DownloadPath]

# Remove cache_middleware log
cm_logger.remove(0)

logger = NewFileLogger(__file__, True)

# FoundResult
MATCH_NO      = 0
MATCH_FUZZY   = 1
MATCH_PART    = 2
MATCH_EXACTLY = 3

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

last_cache_update_time = datetime.datetime.now()
cleaned_title_cache_list = []
author_cache_list = []
cache_lock = threading.RLock()  # 保护缓存访问的可重入锁
is_reload = True

_MATCH_TEXT = {
    MATCH_NO:      "MATCH_NO",
    MATCH_FUZZY:   "MATCH_FUZZY",
    MATCH_PART:    "MATCH_PART",
    MATCH_EXACTLY: "MATCH_EXACTLY",
}

def match_result_to_text(match_type: int) -> str:
    return _MATCH_TEXT.get(match_type, "ERROR")


# 缓存加载/扫描/保存
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


def _update_global_cache(cleaned_titles: list[str]) -> None:
    """更新全局缓存列表，不清空"""
    global cleaned_title_cache_list
    with cache_lock:
        if not JUST_LOAD:
            cleaned_title_cache_list.clear()
        cleaned_title_cache_list.extend(cleaned_titles)
        cleaned_title_cache_list = [x.strip() for x in cleaned_title_cache_list
                                    if not x.startswith("_")]

        cleaned_title_cache_list = sorted(set(cleaned_title_cache_list), reverse=True)
        get_author_from_cleaned_title_cache()


def _try_load_titles_from_cache(cache_file_path: Path) -> bool:
    """
    尝试加载有效的缓存

    Returns:
        缓存是否成功加载
    """

    # 文件不存在 或者 文件几乎为空
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
    # 加载成功后，如果 JUST_LOAD，则继续扫描，否则就直接退出
    if not create_cache and _try_load_titles_from_cache(cache_file_path) and not JUST_LOAD:
        return

    # 加载失败（缓存不存在，或者已失效）
    # 从文件系统收集
    logger.debug("Collecting cleaned titles from filesystem...")
    cleaned_titles = _collect_cleaned_titles_from_filesystem()

    # 更新全局缓存
    _update_global_cache(cleaned_titles)

    # 保存全局缓存，注意，并不是刚刚收集的
    cache = TitlesCache(createTime=datetime.datetime.now(), titles=cleaned_title_cache_list)
    cache.save(cache_file_path)

    logger.debug(
        f"Cache created/refreshed with {len(cleaned_title_cache_list)} cleaned titles, "
        f"authorCache length: {len(author_cache_list)}"
    )
    return cache


# 匹配函数
def check_author_in_title(title: str, author: str):
    return author == "" or author in title


def extract_number_from_string(s: str) -> int | None:
    parts = s.split(' ')
    parts.reverse()
    for p in parts:
        match = re.search(r'\d+', p)
        if match:
            return int(match.group())
    return None


def extract_number_range_from_string(s: str) -> tuple[int, int] | None:
    if '-' not in s and '~' not in s:
        return None

    match = re.search(r'(\d+)\s?[~-]\s?(\d+)(?!\S)', s)
    if match:
        start = int(match.group(1))
        end = int(match.group(2))
        if start <= end:
            return start, end
    return None


def exactly_match(cached_title: str, input_title: str) -> tuple[bool, str]:
    if not cached_title or not input_title:
        return False, ""

    if input_title in cached_title:
        return True, cached_title

    range_match = extract_number_range_from_string(cached_title)
    if not range_match:
        return False, ""

    range_start, range_end = range_match
    query_number = extract_number_from_string(input_title)
    if query_number is None or query_number < range_start or query_number > range_end:
        return False, ""

    query_without_number = input_title.replace(str(query_number), "")
    if query_without_number and query_without_number in cached_title:
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


async def query_match_title(input_title: str, input_author: str = "") -> tuple[int, str]:
    if input_title == "":
        return MATCH_NO, ""

    # 复制缓存列表以减少锁持有时间
    with cache_lock:
        cached_titles = cleaned_title_cache_list.copy()

    match_type = MATCH_NO
    matched_title = "<empty>"

    # EXACTLY MATCH, title in cached_title
    for cached_title in cached_titles:
        # if title in cached_title, 视为EXACTLY，和author判断不太一样
        ok, matched = exactly_match(cached_title, input_title)
        if ok and check_author_in_title(cached_title, input_author):
            match_type = MATCH_EXACTLY
            matched_title = cached_title
            break

    # PART MATCH, part of title in cached_title
    if not match_type:
        for cached_title in cached_titles:
            ok, matched = part_match(cached_title, input_title)
            if ok:
                match_type = MATCH_PART
                matched_title = cached_title
                logger.debug(f"PART MATCH : {matched} in {cached_title}")
                break

    # FUZZY MATCH, title is fuzzy matched with one of cleaned_title_cache_list
    if not match_type:
        ok, matched = fuzz_match(cached_titles, input_title, input_author)
        if ok:
            match_type = MATCH_FUZZY
            matched_title = matched

    logger.debug(f"Match Result : {match_result_to_text(match_type)}, {matched_title}")

    return match_type, matched_title


async def query_author(author: str):
    lower_author = author.lower()
    for cached_author in author_cache_list:
        if lower_author == cached_author:
            return MATCH_EXACTLY
    for cached_author in author_cache_list:
        if lower_author in cached_author:
            return MATCH_PART
    return MATCH_NO


async def refresh_cleaned_title_cache():
    global cleaned_title_cache_list
    while True:
        logger.info("Waiting for 12 hours to refresh cleaned title cache...")
        await asyncio.sleep(CACHE_REFRESH_INTERVAL_SECONDS)  # Refresh every 12 hours
        # cleaned_title_cache_list = []
        logger.info("Refresh cache every 12 hours")
        await load_or_create_cache(create_cache=True)
        logger.info(f"Cleaned title cache refreshed, len: {len(cleaned_title_cache_list)}")


def get_author_from_cleaned_title_cache():
    with cache_lock:
        author_cache_list.clear()
        for cleaned_title in cleaned_title_cache_list:
            author = FindArtistV2(cleaned_title)
            author = author.strip().lower()
            if len(author) == 0 or author in author_cache_list:
                continue
            author_cache_list.append(author)


# FastAPI Server
@asynccontextmanager
async def lifespan(app: FastAPI):
    # start
    logger.debug(f"Reload mode : {is_reload}")
    await load_or_create_cache()
    asyncio.create_task(refresh_cleaned_title_cache())

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


# 统计 request 用时
# @app.middleware('http')
# async def timeCostMiddleware(req: Request, call_next):
#     start = datetime.datetime.now()
#     rsp = await call_next(req)
#     eplased = datetime.datetime.now() - start
#     logger.debug(f"Query use {eplased}")
#     return rsp


@app.get("/")
@DCache(timeout=300)
async def _():
    return JSONResponse(content={"message": f"Hello, World! Cache created/refreshed with {len(cleaned_title_cache_list)} cleaned titles, "
        f"authorCache length: {len(author_cache_list)}"})

def make_response(match_type: int, match_title: str):
    return JSONResponse(content={"title": match_title, "match": match_type})

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

    for ignore in IgnoredNames:
        if ignore in in_title:
            return make_response(MATCH_NO, "")

    match_type, matched_title = await query_match_title(in_title, in_author)
    if match_type:
        logger.debug(f"Query Title, Found '{in_title}' and author '{in_author}', ")
        return make_response(match_type, matched_title)

    logger.debug(f"Query Title, Not Found '{in_title}' and author '{in_author}'")
    return make_response(match_type, "")


@app.post("/query/author")
@DCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    author = data.get("author")

    match_type = await query_author(author)
    if match_type:
        logger.debug(f"Query Author, Found '{author}'")
        return JSONResponse(content={"match": match_type})

    logger.debug(f"Query Author, Not Found : '{author}'")
    return JSONResponse(content={"match": match_type})


@app.post("/query/extract-author")
@DCache(timeout=300)
async def _(request: Request):
    data: dict = await request.json()
    title = data.get("title")
    author = FindArtistV2(title)
    match_type = MATCH_NO if author == "" else MATCH_EXACTLY
    logger.debug(f"Find artist for {title} : {author}")
    return JSONResponse(content={"author": author, "match": match_type})


@app.post("/refresh-cache")
async def refresh_cache_endpoint():
    """手动刷新缓存"""
    try:
        await load_or_create_cache(create_cache=True)
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
        "titles": cleaned_title_cache_list,
        "count": len(cleaned_title_cache_list)
    })


@app.get("/api/authors")
@DCache(timeout=300)
async def get_authors_list():
    """获取所有作者列表"""
    return JSONResponse(content={
        "authors": author_cache_list,
        "count": len(author_cache_list)
    })


@app.get("/api/stats")
@DCache(timeout=300)
async def get_stats():
    """获取缓存统计信息"""
    return JSONResponse(content={
        "cache_count": len(cleaned_title_cache_list),
        "author_count": len(author_cache_list),
        "current_time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.get("/admin")
@DCache(timeout=300)
async def admin_dashboard():
    """管理仪表板页面"""
    cache_count = len(cleaned_title_cache_list)
    author_count = len(author_cache_list)
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


# 托盘图标
myloop = asyncio.new_event_loop()
uvicorn_server = None

def create_image():
    """创建一个简单的托盘图标（绿色背景 + 白字 S）"""
    image = Image.new('RGB', (64, 64), color=(0, 100, 0))
    dc: ImageDraw.ImageDraw = ImageDraw.Draw(image)
    # 使用 anchor="mm" 表示以中心点的中间为锚点，让 S 显示在中央
    dc.text((32, 32), "S", fill=(255, 255, 255), font_size=48, anchor="mm")
    return image


def on_open_web_browser(icon, item):
    import webbrowser
    webbrowser.open("http://localhost:8353/admin")


def on_refresh_cache(icon, item):
    future = asyncio.run_coroutine_threadsafe(load_or_create_cache(create_cache=True), myloop)

    def on_cache_refreshed(f):
        # 缓存刷新完成后更新菜单显示
        try:
            f.result()  # 确保没有异常
            icon.update_menu()  # 强制更新菜单文本
        except (asyncio.CancelledError, RuntimeError) as e:
            # 记录异步任务取消或运行时错误
            logger.warning(f"Cache refresh callback error: {e}")
    future.add_done_callback(on_cache_refreshed)


def on_exit(icon, item):
    icon.stop()
    if is_reload:
        # reload模式要先把父进程杀掉
        parent_pid = os.getppid()
        os.kill(parent_pid, signal.SIGTERM)
    self_pid = os.getpid()
    os.kill(self_pid, signal.SIGTERM)


def setup_tray_icon():
    image = create_image()

    def make_menu():
        # 动态生成菜单，每次弹出时更新缓存数量显示
        # 使用lambda动态获取当前缓存数量
        return pystray.Menu(
            pystray.MenuItem("打开管理页面 (localhost:8353/admin)", on_open_web_browser),
            pystray.MenuItem(
                lambda text: f"立即刷新缓存 ({len(cleaned_title_cache_list)})",
                on_refresh_cache
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", on_exit)
        )

    icon = pystray.Icon("dataserver", image, "server (8353)", make_menu())
    icon.run()


def start_tray_in_thread():
    """在后台线程中启动托盘图标"""
    tray_thread = threading.Thread(target=setup_tray_icon, daemon=True)
    tray_thread.start()
    return tray_thread


def run_uvicorn_in_thread():
    global uvicorn_server
    # 在单独线程中运行 uvicorn，避免阻塞主线程
    config = uvicorn.Config(app, host="127.0.0.1", port=8353, log_level="info", reload=True)
    uvicorn_server = uvicorn.Server(config)
    myloop.run_until_complete(uvicorn_server.serve())


def start_myloop_background():
    """在后台线程中启动 myloop，用于托盘图标回调"""
    if not myloop.is_running():
        def run_loop():
            myloop.run_forever()
        loop_thread = threading.Thread(target=run_loop, daemon=True)
        loop_thread.start()
        logger.debug("Started myloop in background thread for tray callbacks")


def maybe_start_tray():
    # 检查环境变量
    if os.environ.get('DATASERVER_BAT', '').lower() in ('1', 'true', 'yes'):
        logger.debug("Starting tray icon via environment variable DATASERVER_BAT")
        # 确保 myloop 在后台运行以处理回调
        start_myloop_background()
        start_tray_in_thread()


def check_singleton() -> bool:
    # 检查端口 8353 是否已被占用
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', 8353))
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


if __name__ == "__main__":
    # run by python dataserver.py
    if check_singleton():
        sys.exit(0)

    is_reload = False

    # 启动 FastAPI 服务（在线程中）
    uvicorn_thread = threading.Thread(target=run_uvicorn_in_thread, daemon=True)
    uvicorn_thread.start()

    # 直接通过命令行 python dataserver.py 启动，不打开托盘图标
    # uvicorn_thread.join() # 不 join，直接通过 sleep 循环等待
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        sys.exit(0)
else:
    # run by uvicron
    maybe_start_tray()

"""服务器 — FastAPI app、路由、中间件、ServerManager、check_singleton"""

import asyncio
import datetime
import json
import os
import signal
import socket
import sys
import threading
import time
import traceback
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import pystray
import uvicorn
from cache_middleware import CacheMiddleware, MemoryBackend
from cache_middleware import cache as DCache
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image, ImageDraw

from config import IgnoredNames
from pkg.cache import cache_store
from pkg.constants import (
    CACHE_MIN_REFRESH_INTERVAL_HOURS,
    ENABLE_DCACHE,
    ENABLE_RECORD_BATCH_REQUEST,
    MATCH_EXACTLY,
    MATCH_NO,
    logger,
    now_cst,
)
from pkg.query import (
    extract_artist,
    process_batch_request,
    query_author,
    query_match_title,
)

# ============================================================
# FastAPI 应用与生命周期
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    # start
    logger.debug(f"Managed by uvicorn: {os.environ.get('TRAY_ICON', '0') == '1'}")
    await cache_store.load_or_create()
    asyncio.create_task(cache_store.refresh_loop())

    # running
    # handle request
    yield

    logger.info("Shutdown")


app = FastAPI(lifespan=lifespan)

if ENABLE_DCACHE:
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


# ============================================================
# 中间件
# ============================================================

# 防止多个请求同时触发缓存刷新
_refresh_lock = asyncio.Lock()


@app.middleware("http")
async def updateCacheMiddleware(req: Request, call_next):
    current_time = now_cst()
    elapsed_time = current_time - cache_store.last_update_time
    refresh_interval = datetime.timedelta(hours=CACHE_MIN_REFRESH_INTERVAL_HOURS)
    if elapsed_time > refresh_interval:
        async with _refresh_lock:
            # 双重检查：获取锁后再次确认是否需要刷新
            if (now_cst() - cache_store.last_update_time) > refresh_interval:
                cache_store.last_update_time = now_cst()
                logger.debug(
                    f"Refresh cache due to {CACHE_MIN_REFRESH_INTERVAL_HOURS} hour passed since last query"
                )
                await cache_store.load_or_create(create_cache=True)
                await memory_backend.close()

    return await call_next(req)


# 统计 request 用时
@app.middleware("http")
async def timeCostMiddleware(req: Request, call_next):
    body = await req.json() if req.method in ("POST", "PUT", "PATCH") else None
    start = now_cst()
    rsp: Response = await call_next(req)
    eplased = now_cst() - start
    logger.debug(f"Query use {eplased.microseconds / 1000}ms")

    if (
        ENABLE_RECORD_BATCH_REQUEST
        and req.url.path.startswith("/query/batch")
        and body is not None
        and eplased.microseconds / 1000 >= 150
    ):
        record = {"req_body": json.dumps(body), "timeused": eplased.microseconds / 1000}
        with open("tmp/batch_record.json", "+a", encoding="utf-8") as fp:  # noqa: ASYNC230
            json.dump(record, fp)
            fp.write("\n")

    return rsp


# ============================================================
# 辅助函数
# ============================================================


def make_response(match_status: int, match_title: str) -> JSONResponse:
    return JSONResponse(content={"title": match_title, "match": match_status})


# ============================================================
# API 路由
# ============================================================


@app.get("/")
@DCache(timeout=300)
async def root_endpoint():
    return JSONResponse(
        content={
            "message": "Hello, World! Cache created/refreshed with"
            f" {len(cache_store.titles)} cleaned titles,"
            f" authorCache length: {len(cache_store.authors)}"
        }
    )


@app.post("/query/match-title")
@DCache(timeout=300)
async def match_title_endpoint(request: Request):
    data: dict = await request.json()
    in_author = data.get("author")
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


# 单次http请求处理大量的request
@app.post("/query/batch")
@DCache(timeout=300)
async def batch_endpoint(request: Request):
    data: dict = await request.json()
    requests_list: list[dict] = data.get("requests")

    if not requests_list:
        return JSONResponse(
            content={"error": "Missing or empty 'requests' field"}, status_code=422
        )

    # 并发处理所有请求，保持输入顺序
    tasks = [process_batch_request(req) for req in requests_list]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for i, result in enumerate(gathered):
        if isinstance(result, Exception):
            traceback.print_exception(result)
            logger.error(
                f"Batch request error for '{requests_list[i].get('type', '')}': {result}"
            )
            results.append(
                {"type": requests_list[i].get("type", ""), "error": str(result)}
            )
        else:
            results.append(result)

    return JSONResponse(content={"results": results})


@app.post("/query/match-author")
@DCache(timeout=300)
async def match_author_endpoint(request: Request):
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
async def extract_author_endpoint(request: Request):
    data: dict = await request.json()
    title = data.get("title")
    author = await extract_artist(title)
    match_status = MATCH_NO if author == "" else MATCH_EXACTLY
    logger.debug(f"Find artist for {title} : {author}")
    return JSONResponse(content={"author": author, "match": match_status})


@app.post("/refresh-cache")
async def refresh_cache_endpoint():
    """手动刷新缓存"""
    try:
        await cache_store.load_or_create(create_cache=True)
        return JSONResponse(
            content={"success": True, "message": "Cache refreshed successfully"}
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Failed to refresh cache: {e}")
        return JSONResponse(
            content={"success": False, "message": f"Cache refresh failed: {e}"},
            status_code=500,
        )


@app.get("/api/titles")
@DCache(timeout=300)
async def get_titles_list():
    """获取所有清理后的标题列表"""
    return JSONResponse(
        content={"titles": cache_store.titles, "count": len(cache_store.titles)}
    )


@app.get("/api/authors")
@DCache(timeout=300)
async def get_authors_list():
    """获取所有作者列表"""
    return JSONResponse(
        content={"authors": cache_store.authors, "count": len(cache_store.authors)}
    )


@app.get("/api/stats")
@DCache(timeout=300)
async def get_stats():
    """获取缓存统计信息"""
    return JSONResponse(
        content={
            "cache_count": len(cache_store.titles),
            "author_count": len(cache_store.authors),
            "current_time": now_cst().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


@app.get("/admin")
@DCache(timeout=300)
async def admin_dashboard():
    """管理仪表板页面"""
    cache_count = len(cache_store.titles)
    author_count = len(cache_store.authors)
    current_time = now_cst().strftime("%Y-%m-%d %H:%M:%S")

    # 注意：templates 目录在项目根目录，server.py 在 pkg/ 子目录下
    template_path = Path(__file__).parent.parent / "templates/admin.html"
    try:
        with open(template_path, "r", encoding="utf-8") as f:  # noqa: ASYNC230
            html_content = f.read()

        # 替换模板变量
        html_content = html_content.replace("{cache_count}", str(cache_count))
        html_content = html_content.replace("{author_count}", str(author_count))
        html_content = html_content.replace("{current_time}", current_time)

        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        logger.error(f"Template file not found: {template_path}")
        # 返回一个简单的错误页面
        return HTMLResponse(
            content=f"""
            <html><body>
                <h1>Error: Template file not found</h1>
                <p>Please create templates/admin.html</p>
                <p>Cache stats: {cache_count} titles, {author_count} authors</p>
            </body></html>
        """,
            status_code=500,
        )


# ============================================================
# 服务器生命周期管理 — ServerManager
# ============================================================


class ServerManager:
    """FastAPI 服务器生命周期管理器。

    统一管理事件循环、服务器启动和系统托盘。
    使启动/停止逻辑内聚。
    """

    def __init__(self, app: FastAPI, host: str = "127.0.0.1", port: int = 8353):
        self.app = app
        self.host = host
        self.port = port
        self.loop = asyncio.new_event_loop()
        self.uvicorn_server: uvicorn.Server | None = None
        self._managed_by_uvicorn = False

    # ================================================================
    # 事件循环 / uvicorn
    # ================================================================

    def _serve(self) -> None:
        """在事件循环中运行 uvicorn 服务器（阻塞调用线程）。"""
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port, log_level="info"
        )
        self.uvicorn_server = uvicorn.Server(config)
        self.loop.run_until_complete(self.uvicorn_server.serve())

    # ================================================================
    # 托盘图标
    # ================================================================

    @staticmethod
    def _create_tray_image() -> Image.Image:
        """创建一个简单的托盘图标（绿色背景 + 白字 S）。"""
        image = Image.new("RGB", (64, 64), color=(0, 100, 0))
        dc: ImageDraw.ImageDraw = ImageDraw.Draw(image)
        dc.text((32, 32), "S", fill=(255, 255, 255), font_size=48, anchor="mm")
        return image

    def _on_open_browser(self, icon, item) -> None:
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
        if self._managed_by_uvicorn:
            parent_pid = os.getppid()
            os.kill(parent_pid, signal.SIGTERM)
        self_pid = os.getpid()
        os.kill(self_pid, signal.SIGTERM)

    def _setup_tray(self) -> None:
        image = self._create_tray_image()

        def make_menu():
            return pystray.Menu(
                pystray.MenuItem(
                    f"打开管理页面 (localhost:{self.port}/admin)", self._on_open_browser
                ),
                pystray.MenuItem(
                    lambda text: f"立即刷新缓存 ({len(cache_store.titles)})",
                    self._on_refresh_cache,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self._on_exit),
            )

        icon = pystray.Icon("dataserver", image, f"server ({self.port})", make_menu())
        icon.run()

    def start_tray(self) -> threading.Thread:
        """在后台线程启动系统托盘图标（用于 uvicorn --reload 模式）。"""
        self._managed_by_uvicorn = True
        tray_thread = threading.Thread(target=self._setup_tray, daemon=True)
        tray_thread.start()
        return tray_thread

    # ================================================================
    # 启动入口
    # ================================================================

    def run(self) -> None:
        """
        直接启动服务器(python dataserver_v2.py 路径)
        在守护线程中启动 uvicorn,主线程保持进程存活直到被中断
        """
        if check_singleton(self.port):
            sys.exit(0)
        self._managed_by_uvicorn = False
        server_thread = threading.Thread(target=self._serve, daemon=True)
        server_thread.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
            sys.exit(0)


# ============================================================
# 单例检测
# ============================================================


def check_singleton(port: int = 8353) -> bool:
    """检查端口是否已被占用（防止重复启动）。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        if result == 0:
            print("⚠️  Server already running on port 8353")
            print("   Another instance of dataserver is already running.")
            print("   Exiting this instance.")
            return True
    except (TimeoutError, OSError) as e:
        print(f"⚠️  Port check error: {e}")
        return False
        # 继续运行，不因检测错误而退出


# --- 模块级单例 ---
server = ServerManager(app, host="127.0.0.1", port=8353)

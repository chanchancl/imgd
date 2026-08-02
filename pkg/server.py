"""服务器 — FastAPI app、路由、中间件"""

import asyncio
import datetime
import json
import os
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from cache_middleware import CacheMiddleware, MemoryBackend
from cache_middleware import cache as DCache
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

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
from pkg.models import (
    AuthorsResponse,
    BatchRequest,
    ExtractAuthorRequest,
    MatchAuthorRequest,
    MatchTitleRequest,
    QueryResponse,
    RefreshCacheResponse,
    RootResponse,
    StatsResponse,
    TitlesResponse,
)
from pkg.query import (
    extract_artist,
    process_batch_request,
    query_author,
    query_match_title,
)
from pkg.server_manager import request_stats, server

# 预加载 admin 模板（避免端点中同步 I/O 阻塞事件循环）
_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
try:
    _ADMIN_HTML = (_TEMPLATE_DIR / "admin.html").read_text(encoding="utf-8")
except FileNotFoundError:
    _ADMIN_HTML = None

# ============================================================
# FastAPI 应用与生命周期
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    # start
    logger.debug(f"Managed by uvicorn: {os.environ.get('TRAY_ICON', '0') == '1'}")
    await cache_store.load_or_create()
    refresh_task = asyncio.create_task(cache_store.refresh_loop())

    # running
    # handle request
    yield

    # shutdown
    logger.info("Shutting down background tasks...")
    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        logger.info("Background refresh task cancelled")
    logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan)
server.app = app  # 回填 app 引用到启动管理器

memory_backend = None
if ENABLE_DCACHE:
    memory_backend = MemoryBackend(max_size=1000)
    app.add_middleware(CacheMiddleware, backend=memory_backend)


# Allow CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=86400,
)


# ============================================================
# 中间件
# ============================================================

# 防止并发触发缓存刷新
_refresh_lock = asyncio.Lock()


@app.middleware("http")
async def updateCacheMiddleware(req: Request, call_next):
    current_time = now_cst()
    elapsed_time = current_time - cache_store.last_update_time
    refresh_interval = datetime.timedelta(hours=CACHE_MIN_REFRESH_INTERVAL_HOURS)
    if elapsed_time > refresh_interval:
        async with _refresh_lock:
            # 双重检查：获取锁后再次确认
            if (now_cst() - cache_store.last_update_time) > refresh_interval:
                cache_store.last_update_time = now_cst()
                logger.debug(
                    f"Refresh cache due to {CACHE_MIN_REFRESH_INTERVAL_HOURS} hour passed since last query"
                )
                await cache_store.load_or_create(create_cache=True)
                # 清除 DCache，因为缓存数据已刷新
                if memory_backend != None:
                    await memory_backend.close()

    return await call_next(req)


# 请求计时 + 统计
@app.middleware("http")
async def timeCostMiddleware(req: Request, call_next):
    start = time.perf_counter()
    rsp = await call_next(req)
    elapsed = time.perf_counter() - start
    elapsed_ms = elapsed * 1000
    logger.debug(f"Query use {elapsed_ms:.2f}ms")

    # 只统计 /query 开头的业务 API
    if req.url.path.startswith("/query"):
        request_stats.record(req.method, req.url.path, elapsed_ms)

    if (
        ENABLE_RECORD_BATCH_REQUEST
        and req.url.path.startswith("/query/batch")
        and elapsed_ms >= 150
    ):
        try:
            os.makedirs("tmp", exist_ok=True)
            with open("tmp/batch_record.json", "+a", encoding="utf-8") as fp:  # noqa: ASYNC230
                json.dump({"timeused": elapsed_ms}, fp)
                fp.write("\n")
        except OSError as e:
            logger.warning(f"Failed to write batch record: {e}")

    return rsp


# ============================================================
# 路由定义
# ============================================================


# 根路由
@app.get("/", response_model=RootResponse)
@DCache(timeout=300)
async def root_endpoint():
    snap = cache_store.get_snapshot()
    return {
        "message": "Hello, World! Cache created/refreshed with"
        f" {len(snap.titles)} cleaned titles,"
        f" authorCache length: {len(snap.authors)}"
    }


# --- /query ---
query_router = APIRouter(prefix="/query", tags=["query"])


@query_router.post("/match-title", response_model=QueryResponse)
@DCache(timeout=300)
async def match_title_endpoint(req: MatchTitleRequest):
    in_title = req.title
    in_author = req.author

    in_title = in_title.replace("?", "_")  # ? is invalid character in windows path

    for ignoreKeyword in IgnoredNames:
        if ignoreKeyword in in_title:
            return {"title": "", "match": MATCH_NO}

    match_status, matched_title = await query_match_title(in_title, in_author)
    if match_status:
        logger.debug(f"Query Title, Found '{in_title}' and author '{in_author}', ")
        return {"title": matched_title, "match": match_status}

    logger.debug(f"Query Title, Not Found '{in_title}' and author '{in_author}'")
    return {"title": "", "match": match_status}


@query_router.post("/batch")
@DCache(timeout=300)
async def batch_endpoint(batch: BatchRequest):
    # 并发处理，return_exceptions=True 保证单个失败不影响其他任务
    tasks = [process_batch_request(req) for req in batch.requests]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for i, result in enumerate(gathered):
        req_type = batch.requests[i].type
        if isinstance(result, Exception):
            traceback.print_exception(result)
            logger.error(f"Batch request error for '{req_type}': {result}")
            results.append({"type": req_type, "error": str(result)})
        else:
            results.append(result)

    return JSONResponse(content={"results": results})


@query_router.post("/match-author", response_model=QueryResponse)
@DCache(timeout=300)
async def match_author_endpoint(req: MatchAuthorRequest):
    author = req.author
    match_status = await query_author(author)
    if match_status:
        logger.debug(f"Query Author, Found '{author}'")
    else:
        logger.debug(f"Query Author, Not Found : '{author}'")
    return {"match": match_status}


@query_router.post("/extract-author", response_model=QueryResponse)
@DCache(timeout=300)
async def extract_author_endpoint(req: ExtractAuthorRequest):
    title = req.title
    author = await extract_artist(title)
    match_status = MATCH_NO if author == "" else MATCH_EXACTLY
    logger.debug(f"Find artist for {title} : {author}")
    return {"author": author, "match": match_status}


# --- /api ---
api_router = APIRouter(prefix="/api", tags=["api"])


@api_router.get("/titles", response_model=TitlesResponse)
@DCache(timeout=300)
async def get_titles_list():
    """获取所有清理后的标题列表"""
    snap = cache_store.get_snapshot()
    return {"titles": snap.titles, "count": len(snap.titles)}


@api_router.get("/authors", response_model=AuthorsResponse)
@DCache(timeout=300)
async def get_authors_list():
    """获取所有作者列表"""
    snap = cache_store.get_snapshot()
    return {"authors": snap.authors, "count": len(snap.authors)}


@api_router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """获取缓存统计信息与请求统计"""
    snap = cache_store.get_snapshot()
    stats_data = request_stats.get_stats()
    return {
        "cache_count": len(snap.titles),
        "author_count": len(snap.authors),
        "current_time": now_cst().strftime("%Y-%m-%d %H:%M:%S"),
        "request_stats": stats_data,
    }


# --- /admin & 管理功能 ---
admin_router = APIRouter(tags=["admin"])


@admin_router.post("/refresh-cache", response_model=RefreshCacheResponse)
async def refresh_cache_endpoint():
    """手动刷新缓存"""
    try:
        await cache_store.load_or_create(create_cache=True)
        return {"success": True, "message": "Cache refreshed successfully"}
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Failed to refresh cache: {e}")
        return JSONResponse(
            content={"success": False, "message": f"Cache refresh failed: {e}"},
            status_code=500,
        )


@admin_router.get("/admin")
@DCache(timeout=300)
async def admin_dashboard():
    """管理仪表板页面"""
    snap = cache_store.get_snapshot()
    cache_count = len(snap.titles)
    author_count = len(snap.authors)
    current_time = now_cst().strftime("%Y-%m-%d %H:%M:%S")

    if _ADMIN_HTML is None:
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

    html = _ADMIN_HTML.replace("{cache_count}", str(cache_count))
    html = html.replace("{author_count}", str(author_count))
    html = html.replace("{current_time}", current_time)
    return HTMLResponse(content=html)


app.include_router(query_router)
app.include_router(api_router)
app.include_router(admin_router)

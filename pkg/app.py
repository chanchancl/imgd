"""FastAPI 应用 — 生命周期、中间件、路由注册"""

import asyncio
import datetime
import json
import os
import time
from contextlib import asynccontextmanager

from cache_middleware import CacheMiddleware, MemoryBackend
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from pkg.cache import cache_store
from pkg.constants import (
    CACHE_MIN_REFRESH_INTERVAL_HOURS,
    ENABLE_DCACHE,
    ENABLE_RECORD_BATCH_REQUEST,
    logger,
    now_cst,
)
from pkg.manager import request_stats, server
from pkg.routes import admin_router, api_router, query_router, root_router

# -- 生命周期 ----------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.debug(f"Managed by uvicorn: {os.environ.get('TRAY_ICON', '0') == '1'}")
    await cache_store.load_or_create()
    refresh_task = asyncio.create_task(cache_store.refresh_loop())
    yield
    logger.info("Shutting down background tasks...")
    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        logger.info("Background refresh task cancelled")
    logger.info("Shutdown complete")


# -- app ---------------------------------------------------------------


app = FastAPI(lifespan=lifespan)
server.app = app

memory_backend = None
if ENABLE_DCACHE:
    memory_backend = MemoryBackend(max_size=1000)
    app.add_middleware(CacheMiddleware, backend=memory_backend)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=86400,
)


# -- 中间件 ------------------------------------------------------------


_refresh_lock = asyncio.Lock()


@app.middleware("http")
async def updateCacheMiddleware(req: Request, call_next):
    current_time = now_cst()
    elapsed_time = current_time - cache_store.last_update_time
    refresh_interval = datetime.timedelta(hours=CACHE_MIN_REFRESH_INTERVAL_HOURS)
    if elapsed_time > refresh_interval:
        async with _refresh_lock:
            if (now_cst() - cache_store.last_update_time) > refresh_interval:
                cache_store.last_update_time = now_cst()
                logger.debug(
                    f"Refresh cache due to {CACHE_MIN_REFRESH_INTERVAL_HOURS} hour passed since last query"
                )
                await cache_store.load_or_create(create_cache=True)
                if memory_backend is not None:
                    await memory_backend.close()
    return await call_next(req)


@app.middleware("http")
async def timeCostMiddleware(req: Request, call_next):
    start = time.perf_counter()
    rsp = await call_next(req)
    elapsed = time.perf_counter() - start
    elapsed_ms = elapsed * 1000
    logger.debug(f"Query use {elapsed_ms:.2f}ms")

    if req.url.path.startswith("/query"):
        request_stats.record(req.method, req.url.path, elapsed_ms)

    if (
        ENABLE_RECORD_BATCH_REQUEST
        and req.url.path.startswith("/query/batch")
        and elapsed_ms >= 150
    ):
        try:
            body = await req.body()
            os.makedirs("tmp", exist_ok=True)
            with open("tmp/batch_record.json", "+a", encoding="utf-8") as fp:  # noqa: ASYNC230
                json.dump({"req_body": body.decode("utf-8"), "timeused": elapsed_ms}, fp)
                fp.write("\n")
        except OSError as e:
            logger.warning(f"Failed to write batch record: {e}")

    return rsp


# -- 路由注册 ----------------------------------------------------------

app.include_router(query_router)
app.include_router(api_router)
app.include_router(admin_router)
app.include_router(root_router)

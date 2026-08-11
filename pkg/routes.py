"""路由处理函数"""

import asyncio
import json
import traceback
from pathlib import Path

from cache_middleware import cache as DCache
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from pkg.cache import cache_store
from pkg.constants import (
    MATCH_EXACTLY,
    MATCH_NO,
    logger,
    now_cst,
)
from pkg.matching import _sanitize_title, is_title_ignored
from pkg.models import (
    AuthorsResponse,
    BatchRequest,
    ExtractAuthorRequest,
    MatchAuthorRequest,
    MatchTitleRequest,
    OpenTitlesResponse,
    QueryResponse,
    RefreshCacheResponse,
    RootResponse,
    StatsResponse,
    TabCloseBatchRequest,
    TabOpenBatchRequest,
    TabsActionResponse,
    TitlesResponse,
)
from pkg.query import (
    extract_artist,
    process_batch_request,
    query_author,
    query_match_title,
)
from pkg.tabs import open_tabs_store

# -- admin 模板热加载 ---------------------------------------------------

_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "admin.html"
_admin_mtime = 0.0
_admin_cache: str | None = None


def _load_admin() -> str | None:
    global _admin_mtime, _admin_cache
    try:
        mtime = _TEMPLATE_PATH.stat().st_mtime
    except FileNotFoundError:
        return None
    if mtime != _admin_mtime:
        _admin_cache = _TEMPLATE_PATH.read_text(encoding="utf-8")
        _admin_mtime = mtime
    return _admin_cache


# -- routers -----------------------------------------------------------

root_router = APIRouter(tags=["root"])
query_router = APIRouter(prefix="/query", tags=["query"])
api_router = APIRouter(prefix="/api", tags=["api"])
admin_router = APIRouter(tags=["admin"])


# -- / ------------------------------------------------------------------


@root_router.get("/", response_model=RootResponse)
@DCache(timeout=300)
async def root_endpoint():
    snap = cache_store.get_snapshot()
    msg = (
        f"Hello, World! Cache created/refreshed with"
        f" {len(snap.titles)} cleaned titles,"
        f" authorCache length: {len(snap.authors)}"
    )
    return {"message": msg}


# -- /query -------------------------------------------------------------


@query_router.post("/match-title", response_model=QueryResponse)
@DCache(timeout=300)
async def match_title(req: MatchTitleRequest):
    in_title = _sanitize_title(req.title)
    if is_title_ignored(in_title):
        return {"title": "", "match": MATCH_NO}
    match_status, matched_title = await query_match_title(in_title, req.author)
    logger.debug(
        f"Query Title, {'Found' if match_status else 'Not Found'}"
        f" '{in_title}' author '{req.author}'"
    )
    return {"title": matched_title, "match": match_status}


@query_router.post("/match-author", response_model=QueryResponse)
@DCache(timeout=300)
async def match_author(req: MatchAuthorRequest):
    match_status = await query_author(req.author)
    logger.debug(f"Query Author, {'Found' if match_status else 'Not Found'}: '{req.author}'")
    return {"match": match_status}


@query_router.post("/extract-author", response_model=QueryResponse)
@DCache(timeout=300)
async def extract_author(req: ExtractAuthorRequest):
    author = await extract_artist(req.title)
    match_status = MATCH_NO if author == "" else MATCH_EXACTLY
    logger.debug(f"Find artist for {req.title} : {author}")
    return {"author": author, "match": match_status}


@query_router.post("/batch")
@DCache(timeout=300)
async def batch(req: BatchRequest):
    tasks = [process_batch_request(r) for r in req.requests]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    results = []
    for i, result in enumerate(gathered):
        req_type = req.requests[i].type
        if isinstance(result, Exception):
            traceback.print_exception(result)
            logger.error(f"Batch request error for '{req_type}': {result}")
            results.append({"type": req_type, "error": str(result)})
        else:
            results.append(result)
    return JSONResponse(content={"results": results})


# -- /api ---------------------------------------------------------------


@api_router.get("/titles", response_model=TitlesResponse)
@DCache(timeout=300)
async def titles():
    snap = cache_store.get_snapshot()
    return {"titles": snap.titles, "count": len(snap.titles)}


@api_router.get("/authors", response_model=AuthorsResponse)
@DCache(timeout=300)
async def authors():
    snap = cache_store.get_snapshot()
    return {"authors": snap.authors, "count": len(snap.authors)}


@api_router.get("/stats", response_model=StatsResponse)
async def stats():
    snap = cache_store.get_snapshot()
    from pkg.manager import request_stats

    stats_data = request_stats.get_stats()
    return {
        "cache_count": len(snap.titles),
        "author_count": len(snap.authors),
        "current_time": now_cst().strftime("%Y-%m-%d %H:%M:%S"),
        "request_stats": stats_data,
    }


# -- /api/tabs (不加 @DCache —— 实时状态) --------------------------------


@api_router.post("/tabs/open", response_model=TabsActionResponse)
async def tabs_open(req: TabOpenBatchRequest):
    for item in req.tabs:
        open_tabs_store.upsert(item.tab_id, item.title, item.url)
    return {"success": True}


@api_router.post("/tabs/close", response_model=TabsActionResponse)
async def tabs_close(req: TabCloseBatchRequest):
    for tab_id in req.tab_ids:
        open_tabs_store.remove(tab_id)
    return {"success": True}


@api_router.post("/tabs/clear", response_model=TabsActionResponse)
async def tabs_clear():
    open_tabs_store.clear()
    return {"success": True}


@api_router.get("/tabs/open-titles", response_model=OpenTitlesResponse)
async def tabs_open_titles():
    titles = open_tabs_store.get_titles()
    return {"titles": titles, "count": len(titles)}


@api_router.get("/tabs")
async def tabs_list():
    return {"tabs": open_tabs_store.get_all()}


# -- /admin -------------------------------------------------------------


@admin_router.post("/refresh-cache", response_model=RefreshCacheResponse)
async def refresh_cache():
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
async def admin():
    snap = cache_store.get_snapshot()
    cache_count = len(snap.titles)
    author_count = len(snap.authors)
    current_time = now_cst().strftime("%Y-%m-%d %H:%M:%S")

    html = _load_admin()
    if html is None:
        return HTMLResponse(
            content=f"""<html><body>
                <h1>Error: Template file not found</h1>
                <p>Please create templates/admin.html</p>
                <p>Cache stats: {cache_count} titles, {author_count} authors</p>
            </body></html>""",
            status_code=500,
        )

    html = html.replace("{cache_count}", str(cache_count))
    html = html.replace("{author_count}", str(author_count))
    html = html.replace("{current_time}", current_time)
    return HTMLResponse(content=html)

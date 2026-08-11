"""查询服务 — query_match_title, query_author, _process_batch_request"""

import asyncio

from autoclassfiy import FindArtistV2
from pkg.cache import cache_store
from pkg.constants import (
    MATCH_EXACTLY,
    MATCH_FUZZY,
    MATCH_NO,
    MATCH_PART,
    logger,
)
from pkg.matching import (
    _sanitize_title,
    check_author_in_title,
    exact_candidates,
    exactly_match,
    fuzz_match,
    fuzzy_candidates,
    is_title_ignored,
    part_match,
)
from pkg.models import BatchRequestItem


async def extract_artist(title: str) -> str:
    """提取标题中的作者名（线程池执行同步 FindArtistV2）"""
    if not isinstance(title, str):
        return ""
    return await asyncio.to_thread(FindArtistV2, title)


async def query_match_title(
    input_title: str, input_author: str = ""
) -> tuple[int, str]:
    """三级匹配流水线：Exact → Part → Fuzzy，逐级回退"""
    # 1 字标题无匹配意义
    if len(input_title) < 2:
        return MATCH_NO, ""

    cached_titles = cache_store.get_snapshot().titles
    match_status = MATCH_NO
    matched_title = "<empty>"
    title_len = len(input_title)
    fuzz = None  # PART 阶段有条件赋值, FUZZY 阶段复用（避免 UnboundLocalError）

    # EXACT — 输入标题是缓存标题的子串
    for idx in exact_candidates(input_title):
        cached_title = cached_titles[idx]
        ok = exactly_match(cached_title, input_title)
        if ok and check_author_in_title(cached_title, input_author):
            match_status = MATCH_EXACTLY
            matched_title = cached_title
            break

    # PART — 公共子串 ≥ 阈值（2字标题跳过，等价于 exact）
    if not match_status and title_len != 2:
        fuzz = fuzzy_candidates(input_title)
        for idx in fuzz:
            cached_title = cached_titles[idx]
            ok, matched = part_match(cached_title, input_title)
            if ok and check_author_in_title(cached_title, input_author):
                match_status = MATCH_PART
                matched_title = cached_title
                logger.debug(f"PART MATCH : {matched} in {cached_title}")
                break

    # FUZZY — difflib 模糊匹配（<=2字标题跳过）
    if not match_status and title_len > 2:
        # fuzz 可能已从 PART 阶段的 fuzzy_candidates 获取，复用避免重复计算
        if fuzz is None:
            fuzz = fuzzy_candidates(input_title)
        candidate_titles = [cached_titles[i] for i in fuzz]
        ok, matched = fuzz_match(candidate_titles, input_title, input_author)
        if ok and check_author_in_title(matched, input_author):
            match_status = MATCH_FUZZY
            matched_title = matched

    return match_status, matched_title


async def query_author(author: str) -> int:
    """作者查询：先 O(1) 集合精确匹配，再 O(n) 子串回退"""
    if not isinstance(author, str) or author == "":
        return MATCH_NO
    lower_author = author.lower()
    snap = cache_store.get_snapshot()

    if lower_author in snap.author_set:  # O(1) 精确匹配
        return MATCH_EXACTLY
    for cached_author in snap.authors:  # O(n) 子串匹配回退
        if lower_author in cached_author:
            return MATCH_PART
    return MATCH_NO


async def process_batch_request(req: BatchRequestItem) -> dict:
    """处理单个 batch 请求，按 type 字段分派到对应处理逻辑"""
    req_type = req.type

    if req_type == "extract-author":
        title = req.title
        author = await extract_artist(title)
        match_status = MATCH_NO if author == "" else MATCH_EXACTLY
        return {"type": req_type, "author": author, "match": match_status}

    elif req_type == "match-author":
        author = req.author
        match_status = await query_author(author)
        return {"type": req_type, "match": match_status}

    elif req_type == "match-title":
        in_author = req.author
        in_title = req.title
        if not in_title:
            return {"type": req_type, "title": "", "match": MATCH_NO}

        in_title = _sanitize_title(in_title)
        if is_title_ignored(in_title):
            return {"type": req_type, "title": "", "match": MATCH_NO}

        match_status, matched_title = await query_match_title(in_title, in_author)
        return {
            "type": req_type,
            "title": matched_title if match_status else "",
            "match": match_status,
        }

    elif req_type == "extract-match-author-and-match-title":
        # 理论上这才是新加的API，上面三个都仅仅是旧API的 BATCH 版本
        # extract-verify-author + match-title
        in_author = req.author.strip()
        in_title = req.title.strip()

        # author 查询（允许空字符串，返回 MATCH_NO）
        out_author = await extract_artist(in_title)
        out_author = out_author if out_author else in_author
        author_match = await query_author(out_author) if in_author else MATCH_NO

        # title 查询（复用 match-title 的过滤逻辑）
        if not in_title:
            title_match = MATCH_NO
        else:
            in_title = _sanitize_title(in_title)
            if is_title_ignored(in_title):
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

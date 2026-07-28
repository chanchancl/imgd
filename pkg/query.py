"""查询服务 — query_match_title, query_author, _process_batch_request"""

import asyncio

from autoclassfiy import FindArtistV2
from config import IgnoredNames
from pkg.cache import _extract_ngrams, cache_store
from pkg.constants import (
    ENABLE_TRIGRAM_INDEX,
    MATCH_EXACTLY,
    MATCH_FUZZY,
    MATCH_NO,
    MATCH_PART,
    logger,
)
from pkg.matching import (
    check_author_in_title,
    exact_candidates,
    exactly_match,
    fuzz_match,
    fuzzy_candidates,
    part_match,
)


async def extract_artist(title: str) -> str:
    """异步提取标题中的作者名。FindArtistV2 是同步函数，放入线程池避免阻塞事件循环。"""
    return await asyncio.to_thread(FindArtistV2, title)


async def query_match_title(
    input_title: str, input_author: str = ""
) -> tuple[int, str]:
    # 1 字标题无匹配意义，直接拒绝
    if len(input_title) < 2:
        return MATCH_NO, ""

    # 无需加锁读取：通过快照获取 titles 的一致性视图（索引由候选函数内部解包）
    cached_titles = cache_store.get_snapshot().titles

    match_status = MATCH_NO
    matched_title = "<empty>"

    title_len = len(input_title)

    # 预计算 n-gram，避免在 _exact_candidates 和 _fuzzy_candidates 中重复计算
    # >=3 字用 trigram，2 字用 bigram，1 字不计算
    if ENABLE_TRIGRAM_INDEX:
        if title_len >= 3:
            input_grams = _extract_ngrams(input_title)
        elif title_len == 2:
            input_grams = _extract_ngrams(input_title, n=2)
        else:
            input_grams = None  # 1 字标题无法切分 n-gram
    else:
        input_grams = None

    # EXACTLY MATCH, input_title 是某个 cached_title 的子字符串
    for idx in exact_candidates(input_title, input_grams):
        cached_title = cached_titles[idx]
        ok = exactly_match(cached_title, input_title)
        if ok and check_author_in_title(cached_title, input_author):
            match_status = MATCH_EXACTLY
            matched_title = cached_title
            break

    # PART MATCH, input_title 与 cached_title 有足够长的公共子串
    # 注意：2 字标题的 part_match 阈值 ceil(2*0.85)=2，等价于 exact match，跳过
    if not match_status and title_len != 2:
        fuzz = fuzzy_candidates(input_title, input_grams)
        for idx in fuzz:
            cached_title = cached_titles[idx]
            ok, matched = part_match(cached_title, input_title)
            if ok and check_author_in_title(cached_title, input_author):
                match_status = MATCH_PART
                matched_title = cached_title
                logger.debug(f"PART MATCH : {matched} in {cached_title}")
                break

    # FUZZY MATCH
    # exact match 已覆盖子串情况，跳过无意义的 fuzz_match
    if not match_status and title_len > 2:
        if fuzz is None:
            fuzz = fuzzy_candidates(input_title, input_grams)
        candidate_titles = [cached_titles[i] for i in fuzz]
        ok, matched = fuzz_match(candidate_titles, input_title, input_author)
        if ok and check_author_in_title(matched, input_author):
            match_status = MATCH_FUZZY
            matched_title = matched

    return match_status, matched_title


async def query_author(author: str) -> int:
    if author == "":
        return MATCH_NO
    lower_author = author.lower()
    snap = cache_store.get_snapshot()

    # O(1) 精确匹配
    if lower_author in snap.author_set:
        return MATCH_EXACTLY
    # O(n) 子串匹配（仅在非精确匹配时回退）
    for cached_author in snap.authors:
        if lower_author in cached_author:
            return MATCH_PART
    return MATCH_NO


async def process_batch_request(req: dict) -> dict:
    """处理单个 batch 请求，支持并发调用。"""
    req_type = req.get("type", "")

    if req_type == "extract-author":
        title: str = req.get("title", "")
        author = await extract_artist(title)
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
            "match": match_status,
        }

    elif req_type == "extract-match-author-and-match-title":
        # 理论上这才是新加的API，上面三个都仅仅是旧API的 BATCH 版本
        # extract-verify-author + match-title
        in_author = req.get("author", "").strip()
        in_title: str = req.get("title", "").strip()

        # author 查询（允许空字符串，返回 MATCH_NO）
        out_author = await extract_artist(in_title)
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

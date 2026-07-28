"""查询服务 — query_match_title, query_author, _process_batch_request"""

from config import IgnoredNames
from autoclassfiy import FindArtistV2

from pkg.constants import (
    MATCH_NO,
    MATCH_EXACTLY,
    MATCH_PART,
    MATCH_FUZZY,
    logger,
)
from pkg.cache import cache_store
from pkg.matching import (
    exactly_match,
    part_match,
    fuzz_match,
    check_author_in_title,
    _exact_candidates,
    _fuzzy_candidates,
)


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
        ok = exactly_match(cached_title, input_title)
        if ok and check_author_in_title(cached_title, input_author):
            match_status = MATCH_EXACTLY
            matched_title = cached_title
            break

    # PART MATCH, input_title 与 cached_title 有足够长的公共子串
    # 使用 trigram 并集过滤：候选标题只需包含 input_title 的任一 trigram
    if not match_status:
        fuzz = _fuzzy_candidates(input_title)
        for idx in fuzz:
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
    for cached_author in cache_store.authors:
        if lower_author == cached_author:
            return MATCH_EXACTLY
    for cached_author in cache_store.authors:
        if lower_author in cached_author:
            return MATCH_PART
    return MATCH_NO


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

"""匹配引擎 — 精确匹配、部分匹配、模糊匹配，以及 trigram 候选过滤"""

import difflib
import math
import re

from config import IgnoredNames
from pkg.cache import _extract_ngrams, cache_store
from pkg.constants import (
    ENABLE_TRIGRAM_INDEX,
    FUZZY_MATCH_LENGTH_THRESHOLD,
    FUZZY_MATCH_THRESHOLD_DEFAULT,
    FUZZY_MATCH_THRESHOLD_SHORT,
    PART_MATCH_LENGTH_THRESHOLD,
    PART_MATCH_THRESHOLD_DEFAULT,
    PART_MATCH_THRESHOLD_SHORT,
)

# ============================================================
# 辅助函数
# ============================================================

# 数字范围分隔符归一化表：将所有变体统一映射到 '-'
_RANGE_SEP_TRANS = str.maketrans(
    {
        "～": "-",
        "〜": "-",
        "－": "-",
        "~": "-",
    }
)


def _normalize_range_separators(s: str) -> str:
    """将各种数字范围分隔符统一转换为 '-'，确保缓存和输入一致匹配。"""
    return s.translate(_RANGE_SEP_TRANS)


def check_author_in_title(title: str, author: str) -> bool:
    return author == "" or author in title


def _sanitize_title(title: str) -> str:
    """将标题中 '?' 替换为 '_'（'?' 是 Windows 非法路径字符）"""
    return title.replace("?", "_")


def is_title_ignored(title: str) -> bool:
    """检查标题是否包含需忽略的关键词"""
    return any(kw in title for kw in IgnoredNames)


def extract_number_from_string(s: str) -> int | None:
    """从字符串中提取数字，优先 #数字 格式，其次末位含数字 token"""
    m = re.search(r"#(\d+)", s)
    if m:
        return int(m.group(1))

    parts = s.split(" ")
    for p in reversed(parts):
        m = re.search(r"\d+", p)
        if m:
            return int(m.group())

    # 兜底：字符串中任意数字
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def extract_number_range_from_string(s: str) -> tuple[int, int] | None:
    """提取数字范围（如 1-3, 01~05），过滤日期和序数词"""
    s = _normalize_range_separators(s)

    for m in re.finditer(r"(\d+)\s*-\s*(\d+)", s):
        start = int(m.group(1))
        end = int(m.group(2))
        if start > end:
            continue

        # 过滤：日期格式（年份 1900-2100）
        if 1900 <= start <= 2100:
            continue

        # 过滤：序数词（1st, 2nd, 21th 等）
        after = s[m.end() : m.end() + 3].lower()
        if re.match(r"(st|nd|rd|th)", after):
            continue

        return start, end

    return None


# ============================================================
# 匹配函数
# ============================================================


def exactly_match(cached_title: str, input_title: str) -> bool:
    """精确匹配：子串包含 或 数字范围匹配"""
    if not cached_title or not input_title:
        return False

    # 归一化分隔符，统一 1-3 / 1~3 / 1～3
    nc = _normalize_range_separators(cached_title)
    ni = _normalize_range_separators(input_title)

    # 直接子串匹配
    if ni in nc:
        return True

    # 数字范围匹配：输入"3" 命中了缓存中的 "1-3" → 提取范围并检查数字是否在范围内
    range_match = extract_number_range_from_string(nc)
    if not range_match:
        return False

    range_start, range_end = range_match
    query_number = extract_number_from_string(ni)
    if query_number is None or query_number < range_start or query_number > range_end:
        return False

    # 确认去掉数字后的剩余部分仍是子串（避免"vol.3" 去数字后 "vol." 不匹配）
    query_without_number = ni.replace(str(query_number), "")
    return bool(query_without_number and query_without_number in nc)


def part_match(cached_title: str, input_title: str) -> tuple[bool, str]:
    if not input_title or not cached_title:
        return False, ""

    threshold = PART_MATCH_THRESHOLD_DEFAULT
    if len(input_title) < PART_MATCH_LENGTH_THRESHOLD:
        threshold = PART_MATCH_THRESHOLD_SHORT

    min_len = math.ceil(len(input_title) * threshold)

    match = difflib.SequenceMatcher(
        None, input_title, cached_title
    ).find_longest_match()
    if match.size >= min_len:
        return True, input_title[match.a : match.a + match.size]

    return False, ""


def fuzz_match(
    cached_titles: list[str], input_title: str, input_author: str
) -> tuple[bool, str]:
    threshold = FUZZY_MATCH_THRESHOLD_DEFAULT
    if len(input_title) < FUZZY_MATCH_LENGTH_THRESHOLD:
        threshold = FUZZY_MATCH_THRESHOLD_SHORT
    matches = difflib.get_close_matches(
        input_title, cached_titles, n=3, cutoff=threshold
    )
    for fuzzy_match in matches:
        if not check_author_in_title(fuzzy_match, input_author):
            continue
        return True, fuzzy_match
    return False, ""


# ============================================================
# n-gram 索引辅助
# ============================================================


# n-gram 索引原理：
# 若字符串 A 是 B 的子串，则 A 的每个 n-gram 必然也是 B 的 n-gram
# → 对查询词的 grams 在索引中取交集即可得到精确候选


def _resolve_grams(
    input_title: str,
) -> tuple[list[str], dict[str, frozenset[int]]] | None:
    """计算标题 n-gram 并返回 (排序后的 gram 列表, 对应索引)。

    无法使用索引时返回 None（ENABLE_TRIGRAM_INDEX=False 或标题太短）。
    """
    if not ENABLE_TRIGRAM_INDEX:
        return None
    title_len = len(input_title)
    if title_len >= 3:
        n, index = 3, cache_store.get_snapshot().trigram_index
    elif title_len == 2:
        n, index = 2, cache_store.get_snapshot().bigram_index
    else:
        return None
    grams = _extract_ngrams(input_title, n=n)
    if not grams:
        return None
    sorted_grams = sorted(grams, key=lambda g: len(index.get(g, frozenset())))
    return sorted_grams, index


def _intersect_index(
    index: dict[str, frozenset[int]], grams: list[str]
) -> frozenset[int]:
    """对全部 gram 的索引集合取交集，任一 gram 缺失则返回空。grams 已按 posting list 大小升序排列"""
    if not grams:
        return frozenset()
    it = iter(grams)
    result = index.get(next(it))
    if result is None:
        return frozenset()
    for gram in it:
        s = index.get(gram)
        if s is None:
            return frozenset()
        result = result & s
        if not result:
            return frozenset()
    return result


def _union_index(
    index: dict[str, frozenset[int]], grams: list[str], max_size: int
) -> frozenset[int]:
    """对全部 gram 的索引集合取并集，超 max_size 返回已收集的部分结果。grams 已按 posting list 大小升序排列"""
    candidates: set[int] = set()
    for gram in grams:
        s = index.get(gram)
        if s:
            candidates.update(s)
            if len(candidates) > max_size:
                return None
    return frozenset(candidates) if candidates else frozenset()


# ============================================================
# 候选过滤函数
# ============================================================


def exact_candidates(input_title: str) -> list[int]:
    """精确候选：包含全部 n-gram 的标题索引，回退全量扫描"""
    snapshot = cache_store.get_snapshot()
    prepared = _resolve_grams(input_title)
    if prepared is None:
        return snapshot.all_indices
    grams, index = prepared
    return sorted(_intersect_index(index, grams))


def fuzzy_candidates(input_title: str) -> list[int]:
    """模糊候选：包含任一 n-gram 的标题索引"""
    snapshot = cache_store.get_snapshot()
    prepared = _resolve_grams(input_title)
    if prepared is None:
        return snapshot.all_indices
    grams, index = prepared
    half = len(snapshot.titles) // 2
    result = _union_index(index, grams, half)
    return snapshot.all_indices if result is None else sorted(result)

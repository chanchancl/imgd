"""匹配引擎 — 精确匹配、部分匹配、模糊匹配，以及 trigram 候选过滤"""

import re
import math
import difflib

from pkg.constants import (
    PART_MATCH_LENGTH_THRESHOLD,
    PART_MATCH_THRESHOLD_DEFAULT,
    PART_MATCH_THRESHOLD_SHORT,
    FUZZY_MATCH_LENGTH_THRESHOLD,
    FUZZY_MATCH_THRESHOLD_DEFAULT,
    FUZZY_MATCH_THRESHOLD_SHORT,
    ENABLE_TRIGRAM_INDEX,
)
from pkg.cache import cache_store, _extract_ngrams


# ============================================================
# 辅助函数
# ============================================================

# 数字范围分隔符归一化表：将所有变体统一映射到 '-'
_RANGE_SEP_TRANS = str.maketrans({
    '～': '-',
    '〜': '-',
    '－': '-',
    '~': '-',
})


def _normalize_range_separators(s: str) -> str:
    """将各种数字范围分隔符统一转换为 '-'，确保缓存和输入一致匹配。"""
    return s.translate(_RANGE_SEP_TRANS)


def check_author_in_title(title: str, author: str) -> bool:
    return author == "" or author in title


def extract_number_from_string(s: str) -> int | None:
    """从字符串中提取数字。
        尝试最后一个空格分隔的含数字 token
        尝试任意位置的数字。
    """
    m = re.search(r'#(\d+)', s)
    if m:
        return int(m.group(1))

    parts = s.split(' ')
    for p in reversed(parts):
        m = re.search(r'\d+', p)
        if m:
            return int(m.group())

    # 兜底：字符串中任意数字
    m = re.search(r'\d+', s)
    return int(m.group()) if m else None


def extract_number_range_from_string(s: str) -> tuple[int, int] | None:
    """从字符串中提取数字范围（如 1-3, 01~05, 1～3）。

    先归一化所有分隔符变体为 '-'，再匹配。过滤日期和序数词。
    """
    s = _normalize_range_separators(s)

    for m in re.finditer(r'(\d+)\s*-\s*(\d+)', s):
        start = int(m.group(1))
        end = int(m.group(2))
        if start > end:
            continue

        # 过滤：日期格式（年份 1900-2100）
        if 1900 <= start <= 2100:
            continue

        # 过滤：序数词（1st, 2nd, 21th 等）
        after = s[m.end():m.end() + 3].lower()
        if re.match(r'(st|nd|rd|th)', after):
            continue

        return start, end

    return None


# ============================================================
# 匹配函数
# ============================================================

def exactly_match(cached_title: str, input_title: str) -> bool:
    if not cached_title or not input_title:
        return False

    # 归一化：统一分隔符，让 1-3 / 1~3 / 1～3 等价
    nc = _normalize_range_separators(cached_title)
    ni = _normalize_range_separators(input_title)

    if ni in nc:
        return True

    range_match = extract_number_range_from_string(nc)
    if not range_match:
        return False

    range_start, range_end = range_match
    query_number = extract_number_from_string(ni)
    if query_number is None or query_number < range_start or query_number > range_end:
        return False

    query_without_number = ni.replace(str(query_number), "")
    if query_without_number and query_without_number in nc:
        return True

    return False


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


# ============================================================
# Trigram 索引候选过滤
# ============================================================

def _exact_candidates(input_title: str) -> list[int]:
    """返回包含 input_title 全部 trigram 的标题索引列表。

    如果 input_title 是某个 cached_title 的子字符串
    那么 input_title 的所有 trigram 必须都出现在该 cached_title 中。
    若输入长度不足 3 个字符，则回退到全量扫描。

    Args:
        input_title: 输入的查询标题

    Returns:
        候选标题索引列表；若无法匹配任何 trigram 则返回空列表
    """
    if not ENABLE_TRIGRAM_INDEX or len(input_title) < 3:
        return list(range(len(cache_store.titles)))

    # 提取输入的所有 trigram
    input_grams = _extract_ngrams(input_title)

    if not input_grams:
        return list(range(len(cache_store.titles)))

    # 对所有 trigram 的索引集合取交集，最后排序以保证确定性的匹配顺序
    it = iter(input_grams)
    first = next(it)
    result_set = cache_store.trigram_index.get(first)
    if result_set is None:
        return []  # 第一个 trigram 就不在任何标题中

    result = set(result_set)  # 转换为可变 set 以便迭代交集
    for gram in it:
        s = cache_store.trigram_index.get(gram)
        if s is None:
            return []  # 某个 trigram 不在任何标题中，不可能有匹配
        result &= s
        if not result:
            return []

    return sorted(result)  # 排序以保持与全量扫描一致的顺序


def _fuzzy_candidates(input_title: str) -> list[int]:
    """返回包含 input_title 任一 trigram 的标题索引列表。

    对于部分匹配和模糊匹配，有效的匹配必须共享至少一个 trigram。
    若候选数量超过缓存总量的一半，则回退到全量扫描以避免过滤开销浪费。
    若输入长度不足 3 个字符，则回退到全量扫描。

    Args:
        input_title: 输入的查询标题

    Returns:
        候选标题索引列表
    """
    if not ENABLE_TRIGRAM_INDEX or len(input_title) < 3:
        return list(range(len(cache_store.titles)))

    half = len(cache_store.titles) // 2
    candidates: set[int] = set()
    for gram in _extract_ngrams(input_title):
        s = cache_store.trigram_index.get(gram)
        if s:
            candidates.update(s)
            if len(candidates) > half:
                # 候选太多，过滤收益不大，直接全量扫描
                return list(range(len(cache_store.titles)))

    if not candidates:
        # 没有任何 trigram 匹配，但为防误判仍需全量扫描
        # return list(range(len(cache_store.titles)))
        return []

    return sorted(candidates)  # 排序以保持与全量扫描一致的顺序

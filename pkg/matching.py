"""匹配引擎 — 精确匹配、部分匹配、模糊匹配，以及 trigram 候选过滤"""

import difflib
import math
import re

from pkg.cache import cache_store
from pkg.constants import (
    ENABLE_TRIGRAM_INDEX,
    FUZZY_MATCH_LENGTH_THRESHOLD,
    FUZZY_MATCH_THRESHOLD_DEFAULT,
    FUZZY_MATCH_THRESHOLD_SHORT,
    PART_MATCH_LENGTH_THRESHOLD,
    PART_MATCH_THRESHOLD_DEFAULT,
    PART_MATCH_THRESHOLD_SHORT,
)
from pkg.models import CacheSnapshot

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


def extract_number_from_string(s: str) -> int | None:
    """从字符串中提取数字。
    尝试最后一个空格分隔的含数字 token
    尝试任意位置的数字。
    """
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
    """从字符串中提取数字范围（如 1-3, 01~05, 1～3）。

    先归一化所有分隔符变体为 '-'，再匹配。过滤日期和序数词。
    """
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


"""
#0, abcdef -> abc bcd cde def
#1, ebcdeg -> ebc bcd cde deg
#2, abcfg  -> abc bcf cfg
#3, 
then  abc -> (0, 2)
      bcd -> (0, 1)
      bcf -> (2)
      cde -> (0, 1, 2)
      def -> (0)
      deg -> (1)
      ebc -> (1)

if we want find cdef, the 3-gram of cdef are "cde" and "def"

we can get (0, 1, 2) and (0)

result = intersect them = (0)

if string A is substring of B
then each n-gram of A must also is a gram of B
"""


def _ngram_index(
    snapshot: CacheSnapshot, input_title: str
) -> dict[str, frozenset[int]] | None:
    """根据标题长度选择对应的 n-gram 索引。

    >=3 字 → trigram 索引
      2 字 → bigram 索引
    """
    # title_len >= 2
    title_len = len(input_title)

    if title_len >= 3:
        return snapshot.trigram_index
    if title_len == 2:
        return snapshot.bigram_index
    return None


def _intersect_index(
    index: dict[str, frozenset[int]], grams: set[str]
) -> frozenset[int]:
    """对全部 gram 的索引集合取交集；任一 gram 不在索引中则返回空。"""
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
    index: dict[str, frozenset[int]], grams: set[str], max_size: int
) -> frozenset[int] | None:
    """对全部 gram 的索引集合取并集；超过 max_size 则返回 None 表示应回退全量扫描。"""
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


def exact_candidates(
    input_title: str, input_grams: set[str] | None = None
) -> list[int]:
    """返回包含 input_title 全部 n-gram 的标题索引列表。

    对 >=3 字标题使用 trigram 索引，2 字标题使用 bigram 索引，
    对 1 字标题回退到全量扫描。
    """
    snapshot = cache_store.get_snapshot()

    if not ENABLE_TRIGRAM_INDEX or input_grams is None:
        return snapshot.all_indices

    index = _ngram_index(snapshot, input_title)
    if index is None:
        return snapshot.all_indices

    return sorted(_intersect_index(index, input_grams))


def fuzzy_candidates(
    input_title: str, input_grams: set[str] | None = None
) -> list[int]:
    """返回包含 input_title 任一 n-gram 的标题索引列表。

    对 >=3 字标题使用 trigram 索引，2 字标题使用 bigram 索引，
    1 字标题回退到全量扫描。
    若候选数量超过缓存总量的一半则回退到全量扫描。
    """
    snapshot = cache_store.get_snapshot()

    if not ENABLE_TRIGRAM_INDEX or input_grams is None:
        return snapshot.all_indices

    index = _ngram_index(snapshot, input_title)
    if index is None:
        return snapshot.all_indices
    half = len(snapshot.titles) // 2
    result = _union_index(index, input_grams, half)
    if result is None:
        return snapshot.all_indices
    return sorted(result)

"""pkg - dataserver 功能模块包"""

from pkg.models import TitlesCache
from pkg.constants import (
    MATCH_NO, MATCH_FUZZY, MATCH_PART, MATCH_EXACTLY,
    match_result_to_text,
    DEBUG, ENABLE_TRIGRAM_INDEX,
)
from pkg.cache import cache_store, CacheStore

# 注意：不在此处 import server，避免名称遮蔽 server 模块。
# 请使用 from pkg.server import server 直接导入。


__all__ = [
    "TitlesCache",
    "MATCH_NO", "MATCH_FUZZY", "MATCH_PART", "MATCH_EXACTLY",
    "match_result_to_text",
    "DEBUG", "ENABLE_TRIGRAM_INDEX",
    "cache_store", "CacheStore",
]

"""pkg - dataserver 功能模块包"""

from pkg.cache import CacheStore, cache_store
from pkg.constants import (
    DEBUG,
    ENABLE_TRIGRAM_INDEX,
    MATCH_EXACTLY,
    MATCH_FUZZY,
    MATCH_NO,
    MATCH_PART,
    match_result_to_text,
)
from pkg.models import TitlesCache

# 注意：不在此处 import server，避免名称遮蔽 server 模块。
# 请使用 from pkg.server import server 直接导入。


__all__ = [
    "DEBUG",
    "ENABLE_TRIGRAM_INDEX",
    "MATCH_EXACTLY",
    "MATCH_FUZZY",
    "MATCH_NO",
    "MATCH_PART",
    "CacheStore",
    "TitlesCache",
    "cache_store",
    "match_result_to_text",
]

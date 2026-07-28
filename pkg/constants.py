"""配置与常量 — 阈值、路径、match_status 枚举"""

from cache_middleware.logger_config import logger as cm_logger
from utils import NewFileLogger

# Remove cache_middleware log
cm_logger.remove(0)

logger = NewFileLogger(__file__, True)

# --- 搜索路径 ---
from config import DownloadPath
searchPath = [DownloadPath]

# --- 匹配阈值 ---
PART_MATCH_LENGTH_THRESHOLD = 10
PART_MATCH_THRESHOLD_DEFAULT = 0.65
PART_MATCH_THRESHOLD_SHORT = 0.85

FUZZY_MATCH_LENGTH_THRESHOLD = 15
FUZZY_MATCH_THRESHOLD_DEFAULT = 0.6
FUZZY_MATCH_THRESHOLD_SHORT = 0.8

# --- 缓存设置 ---
CACHE_MIN_REFRESH_INTERVAL_HOURS = 1
CACHE_PATH = "cache/TitlesCache.json"
CACHE_REFRESH_INTERVAL_SECONDS = 3600 * 12  # 12 hours

# --- 功能开关 ---
DEBUG = False
ENABLE_TRIGRAM_INDEX = True

# --- MatchStatus 枚举 ---
MATCH_NO      = 0
MATCH_FUZZY   = 1
MATCH_PART    = 2
MATCH_EXACTLY = 3

_MATCH_TEXT = {
    MATCH_NO:      "MATCH_NO",
    MATCH_FUZZY:   "MATCH_FUZZY",
    MATCH_PART:    "MATCH_PART",
    MATCH_EXACTLY: "MATCH_EXACTLY",
}


def match_result_to_text(match_status: int) -> str:
    return _MATCH_TEXT.get(match_status, "ERROR")

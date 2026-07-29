
JUST_LOAD = False

ManagedDir = "."  # 主管理目录（递归收集）

ExtraSearchDir = "."  # 额外搜索目录（仅扫描顶层）

LinkPath = "."

# --- 功能开关 ---
DEBUG = False
ENABLE_DCACHE = True  # HTTP 响应缓存（Debug/录慢请求时自动关闭）
ENABLE_RECORD_BATCH_REQUEST = True  # 记录 >150ms 的批处理请求到 tmp/
ENABLE_TRIGRAM_INDEX = True  # trigram 倒排索引加速匹配

if DEBUG or ENABLE_RECORD_BATCH_REQUEST:
    ENABLE_DCACHE = False

IgnoredNames = []

IgnoredArtist = [
    "a"
]

ArtistAlias = [
    "a : b c d,"
]

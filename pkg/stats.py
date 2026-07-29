"""请求统计收集器"""

import threading
import time


def _percentile(sorted_data: list[float], p: float) -> float:
    """计算百分位数（线性插值），空列表返回 0.0"""
    if not sorted_data:
        return 0.0

    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]

    # 线性插值: index = (p/100) * (n-1)
    k = (p / 100.0) * (n - 1)
    f = int(k)
    c = k - f

    if f + 1 >= n:
        return sorted_data[-1]

    return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])


class RequestStatsCollector:
    """请求耗时统计收集器，线程安全。"""

    def __init__(self):
        self._lock = threading.Lock()
        # key: "METHOD /path" (例如 "POST /query/batch")
        # value: list[float] — 每次请求耗时（毫秒）
        self._durations: dict[str, list[float]] = {}
        self._start_time = time.time()

    def record(self, method: str, path: str, duration_ms: float) -> None:
        """记录一次请求耗时（毫秒）"""
        key = f"{method} {path}"
        with self._lock:
            if key not in self._durations:
                self._durations[key] = []
            self._durations[key].append(duration_ms)

    def get_stats(self) -> dict:
        """返回统计数据快照，含 overall 和 per_endpoint 的 min/max/avg/P50/P90/P99"""
        # 锁内快照拷贝 —— 只复制引用结构，极快
        with self._lock:
            durations_snapshot = {k: list(v) for k, v in self._durations.items()}
            uptime = time.time() - self._start_time

        # 锁外计算 —— 排序、百分位等耗时操作
        all_durations: list[float] = []
        for durations in durations_snapshot.values():
            all_durations.extend(durations)

        total_requests = len(all_durations)

        # 按请求数降序排列端点
        sorted_endpoints = sorted(
            durations_snapshot.items(),
            key=lambda item: len(item[1]),
            reverse=True,
        )

        per_endpoint = {
            endpoint: self._calc_summary(durations)
            for endpoint, durations in sorted_endpoints
        }

        overall = self._calc_summary(all_durations)

        return {
            "uptime_seconds": round(uptime, 1),
            "total_requests": total_requests,
            "overall": overall,
            "per_endpoint": per_endpoint,
        }

    @staticmethod
    def _calc_summary(durations: list[float]) -> dict:
        """计算统计数据摘要（min/max/avg/P50/P90/P99）"""
        if not durations:
            return {
                "count": 0,
                "min": 0,
                "max": 0,
                "avg": 0,
                "p50": 0,
                "p90": 0,
                "p99": 0,
            }

        count = len(durations)
        total = sum(durations)
        sorted_data = sorted(durations)

        return {
            "count": count,
            "min": round(sorted_data[0], 2),
            "max": round(sorted_data[-1], 2),
            "avg": round(total / count, 2),
            "p50": round(_percentile(sorted_data, 50), 2),
            "p90": round(_percentile(sorted_data, 90), 2),
            "p99": round(_percentile(sorted_data, 99), 2),
        }

"""Open tabs state — 跟踪浏览器标签页，提供标题列表供客户端匹配"""

from pkg.matching import _sanitize_title


class OpenTabsStore:
    """标签页标题管理器。单线程（FastAPI async event loop），无需加锁。"""

    def __init__(self):
        self._tabs: dict[int, tuple[str, str]] = {}  # tab_id → (title, url)

    def upsert(self, tab_id: int, title: str, url: str = "") -> None:
        self._tabs[tab_id] = (title, url)

    def remove(self, tab_id: int) -> None:
        self._tabs.pop(tab_id, None)

    def clear(self) -> None:
        self._tabs.clear()

    def get_titles(self) -> list[str]:
        titles: set[str] = set()
        for title, _ in self._tabs.values():
            title = _sanitize_title(title.strip())
            if len(title) < 2:
                continue
            titles.add(title)
        return sorted(titles)

    def get_all(self) -> list[dict]:
        return [
            {"tab_id": tid, "title": title, "url": url}
            for tid, (title, url) in self._tabs.items()
        ]


open_tabs_store = OpenTabsStore()

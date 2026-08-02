"""服务器生命周期管理 — ServerManager、单例检测、托盘图标"""

import asyncio
import os
import signal
import socket
import sys
import threading
import time
import webbrowser

import pystray
import uvicorn
from fastapi import FastAPI
from PIL import Image, ImageDraw

from pkg.cache import cache_store
from pkg.constants import logger
from pkg.stats import RequestStatsCollector

request_stats = RequestStatsCollector()


class ServerManager:
    """管理 FastAPI 服务器生命周期和系统托盘。"""

    def __init__(self, app: FastAPI, host: str = "127.0.0.1", port: int = 8353):
        self.app = app
        self.host = host
        self.port = port
        self.loop = asyncio.new_event_loop()
        self.uvicorn_server: uvicorn.Server | None = None
        self._managed_by_uvicorn = False

    # ================================================================
    # 事件循环 / uvicorn
    # ================================================================

    def _serve(self) -> None:
        """在事件循环中运行 uvicorn（阻塞调用线程）"""
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port, log_level="info"
        )
        self.uvicorn_server = uvicorn.Server(config)
        self.loop.run_until_complete(self.uvicorn_server.serve())

    # ================================================================
    # 托盘图标
    # ================================================================

    @staticmethod
    def _create_tray_image() -> Image.Image:
        """创建托盘图标（绿色背景 + 白字 S）"""
        image = Image.new("RGB", (64, 64), color=(0, 100, 0))
        dc: ImageDraw.ImageDraw = ImageDraw.Draw(image)
        dc.text((32, 32), "S", fill=(255, 255, 255), font_size=48, anchor="mm")
        return image

    def _on_open_browser(self, icon, item) -> None:
        webbrowser.open(f"http://{self.host}:{self.port}/admin")

    def _on_refresh_cache(self, icon, item) -> None:
        # 从托盘线程跨线程调度到事件循环执行
        future = asyncio.run_coroutine_threadsafe(
            cache_store.load_or_create(create_cache=True), self.loop
        )

        def on_cache_refreshed(f):
            try:
                f.result()
                icon.update_menu()
            except (asyncio.CancelledError, RuntimeError) as e:
                logger.warning(f"Cache refresh callback error: {e}")

        future.add_done_callback(on_cache_refreshed)

    def _on_exit(self, icon, item) -> None:
        icon.stop()
        # uvicorn --reload 模式下需要 kill 父进程才能真正退出
        if self._managed_by_uvicorn:
            parent_pid = os.getppid()
            os.kill(parent_pid, signal.SIGTERM)
        self_pid = os.getpid()
        os.kill(self_pid, signal.SIGTERM)

    def _setup_tray(self) -> None:
        image = self._create_tray_image()

        def make_menu():
            return pystray.Menu(
                pystray.MenuItem(
                    f"打开管理页面 (localhost:{self.port}/admin)", self._on_open_browser
                ),
                pystray.MenuItem(
                    lambda text: (
                        f"立即刷新缓存 ({len(cache_store.get_snapshot().titles)})"
                    ),
                    self._on_refresh_cache,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda text: (
                        f"请求总数: {request_stats.get_stats()['total_requests']}"
                        f"  |  平均耗时: {request_stats.get_stats()['overall']['avg']}ms"
                    ),
                    None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self._on_exit),
            )

        icon = pystray.Icon("dataserver", image, f"server ({self.port})", make_menu())
        icon.run()

    def start_tray(self) -> threading.Thread:
        """后台线程启动系统托盘（uvicorn --reload 模式用）"""
        self._managed_by_uvicorn = True
        tray_thread = threading.Thread(target=self._setup_tray, daemon=True)
        tray_thread.start()
        return tray_thread

    # ================================================================
    # 启动入口
    # ================================================================

    def run(self) -> None:
        """直接启动服务器（python dataserver.py），守护线程跑 uvicorn"""
        if check_singleton(self.port):
            sys.exit(0)
        self._managed_by_uvicorn = False
        server_thread = threading.Thread(target=self._serve, daemon=True)
        server_thread.start()
        try:
            while True:
                time.sleep(1)
                if not server_thread.is_alive():
                    logger.error("Server thread died unexpectedly, exiting")
                    sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
            sys.exit(0)


# ============================================================
# 单例检测
# ============================================================


def check_singleton(port: int = 8353) -> bool:
    """检查端口是否已被占用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", port))
            if result == 0:
                print("⚠️  Server already running on port 8353")
                print("   Another instance of dataserver is already running.")
                print("   Exiting this instance.")
                return True
    except (TimeoutError, OSError) as e:
        print(f"⚠️  Port check error: {e}")
        return False
        # 继续运行，不因检测错误而退出


# --- 模块级单例 ---
server = ServerManager(None, host="127.0.0.1", port=8353)

"""dataserver 入口

使用方式：
    - 直接运行:   python dataserver.py
    - uvicorn:   uvicorn dataserver:app --reload --host 127.0.0.1 --port 8353
"""

import os

from pkg.app import app
from pkg.manager import server

_ = app

if __name__ == "__main__":
    server.run()
else:
    if os.environ.get("TRAY_ICON", "false") == "true":
        server.start_tray()

"""dataserver v2 — 模块化版本入口

使用方式：
    - 直接运行:   python dataserver_v2.py
    - uvicorn:   uvicorn dataserver_v2:app --reload --host 127.0.0.1 --port 8353
"""

import os
from pkg.server import app, server

if __name__ == "__main__":
    server.run()
else:
    # uvicorn 会直接调用 app 对象启动服务器，所以我们这里只需要处理托盘图标的启动逻辑
    if os.environ.get("TRAY_ICON", "false") == "true":
        server.start_tray()

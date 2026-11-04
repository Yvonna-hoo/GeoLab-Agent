#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GeoLab Agent 启动入口。

    python run.py              # 默认 127.0.0.1:8010
    python run.py --port 8080
    python run.py --host 0.0.0.0 --port 8080   # 局域网内让别人访问演示

无第三方依赖，无需安装。
"""
from __future__ import annotations

import argparse
import sys

from geolab.server import serve


def main() -> int:
    if sys.version_info < (3, 8):
        print("需要 Python 3.8 或更高版本，当前为 %s" % ".".join(map(str, sys.version_info[:3])))
        return 1

    parser = argparse.ArgumentParser(description="GeoLab Agent 本地演示服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8010, help="监听端口，默认 8010")
    args = parser.parse_args()

    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

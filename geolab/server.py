# -*- coding: utf-8 -*-
"""GeoLab Agent 的 HTTP 服务。

只用 Python 标准库：裁判/评审把仓库克隆下来，执行 `python run.py` 就能打开，
不需要 pip install、不需要 Docker、不需要模型 API Key 也能演示完整链路。
"""
from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import unquote, urlparse

from . import service
from .agent import llm_router, router
from .agent.llm import load_config
from .agent.router import COMPARE_PRESETS, DEFAULT_SWEEP_VALUES, TOPIC_SWEEP
from .registry import catalog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

MAX_BODY = 2 * 1024 * 1024  # 2 MB


class Handler(BaseHTTPRequestHandler):
    server_version = "GeoLabAgent/1.0"

    # ---- 基础响应 ----

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError(f"请求体过大（{length} 字节），上限 {MAX_BODY}")
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        return json.loads(raw.decode("utf-8"))

    # ---- 路由 ----

    def do_GET(self) -> None:  # noqa: N802
        path = posixpath.normpath(unquote(urlparse(self.path).path))

        if path == "/api/health":
            cfg = load_config()
            self._json({
                "ok": True,
                "service": "geolab-agent",
                "version": "1.0.0",
                # 前端据此显示「当前是大模型还是规则引擎」，避免让人误以为是同一个东西
                "llm": {
                    "configured": cfg is not None,
                    "model": cfg.model if cfg else None,
                    "base": cfg.base if cfg else None,
                },
            })
            return
        if path == "/api/catalog":
            self._json({"ok": True, "experiments": catalog()})
            return
        if path == "/api/tasks":
            self._json({"ok": True, "tasks": router.tasks()})
            return
        if path == "/api/presets":
            sweep = dict(DEFAULT_SWEEP_VALUES)
            sweep.update(TOPIC_SWEEP)
            self._json({"ok": True, "sweep": sweep, "compare": COMPARE_PRESETS})
            return

        self._serve_static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = posixpath.normpath(unquote(urlparse(self.path).path))
        try:
            payload = self._read_json()
        except Exception as exc:
            self._json({"ok": False, "errors": [{"code": "bad_request", "message": str(exc)}]}, 400)
            return

        try:
            if path == "/api/execute":
                self._json(service.execute(payload))
                return
            if path == "/api/agent/route":
                engine = str(payload.get("engine") or "auto")
                self._json(llm_router.route_with_engine(str(payload.get("text") or ""), engine))
                return
        except Exception as exc:
            self._json({
                "ok": False,
                "errors": [{
                    "code": "internal_error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "detail": traceback.format_exc(limit=3),
                }],
            }, 500)
            return

        self._json({"ok": False, "errors": [{"code": "not_found", "message": f"未知接口 {path}"}]}, 404)

    # ---- 静态文件 ----

    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"

        rel = path.lstrip("/")
        target = os.path.normpath(os.path.join(WEB_DIR, rel))

        # 目录穿越防护
        if not target.startswith(os.path.normpath(WEB_DIR)):
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return

        if not os.path.isfile(target):
            self._send(404, b"404 not found", "text/plain; charset=utf-8")
            return

        ctype, _ = mimetypes.guess_type(target)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"

        with open(target, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def log_message(self, fmt: str, *args: Any) -> None:  # 精简日志
        if "/api/" in (self.path or ""):
            print(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else ''}")


def serve(host: str = "127.0.0.1", port: int = 8010) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print("=" * 58)
    print("  GeoLab Agent — 地理科学虚拟实验智能体")
    print(f"  {url}")
    print("  按 Ctrl+C 停止")
    print("=" * 58)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()

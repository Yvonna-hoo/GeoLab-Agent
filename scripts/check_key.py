#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证模型服务的 key 是否可用。

    python scripts/check_key.py

读取仓库根目录的 .env，发一个极小的请求（max_tokens=5），
只报告状态、延迟和 token 用量——**不会打印 key 的完整内容**。

退出码：0 可用 / 1 不可用
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path: str) -> dict:
    """极简 .env 解析：KEY=VALUE，# 开头为注释。不依赖 python-dotenv。"""
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def mask(secret: str) -> str:
    if not secret:
        return "(空)"
    if len(secret) <= 10:
        return secret[:2] + "*" * max(len(secret) - 2, 0)
    return f"{secret[:5]}…{secret[-4:]}（长度 {len(secret)}）"


def main() -> int:
    env = load_env(os.path.join(ROOT, ".env"))
    # 环境变量优先，方便临时覆盖
    base = (os.environ.get("GEO_API_BASE") or env.get("GEO_API_BASE") or "").rstrip("/")
    key = os.environ.get("GEO_API_KEY") or env.get("GEO_API_KEY") or ""
    model = os.environ.get("GEO_MODEL") or env.get("GEO_MODEL") or ""

    print("=" * 60)
    print(" GeoLab Agent · 模型服务连通性检查")
    print("=" * 60)

    problems = []
    if not base:
        problems.append("GEO_API_BASE 未配置")
    if not key:
        problems.append("GEO_API_KEY 未配置")
    if not model:
        problems.append("GEO_MODEL 未配置")

    print(f" BASE_URL : {base or '(空)'}")
    print(f" API_KEY  : {mask(key)}")
    print(f" MODEL    : {model or '(空)'}")

    if problems:
        print("\n✗ 配置不完整：")
        for p in problems:
            print(f"   · {p}")
        print("\n  请复制 .env.example 为 .env 并填写，再重新运行。")
        return 1

    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：就绪"}],
        "max_tokens": 8,
        "stream": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    # 部分环境有自签证书或代理，这里不做降级，保持默认严格校验
    ctx = ssl.create_default_context()

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        detail = exc.read().decode("utf-8", "replace")[:600]
        print(f"\n✗ HTTP {exc.code}  耗时 {elapsed:.0f} ms")
        hints = {
            401: "key 无效或已撤销 —— 回控制台确认是否复制完整、是否被删除",
            402: "余额不足 —— 到控制台充值",
            403: "无权限 —— 模型未开通，或 key 绑定了别的业务空间",
            404: "接口地址不对 —— 检查 BASE_URL，注意结尾不要多写 /chat/completions",
            429: "触发限流 —— 稍等再试",
        }
        if exc.code in hints:
            print(f"  可能原因：{hints[exc.code]}")
        print(f"  返回：{detail}")
        return 1
    except urllib.error.URLError as exc:
        print(f"\n✗ 网络不可达：{exc.reason}")
        print("  检查本机网络、代理设置，或换一个 BASE_URL。")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n✗ 调用失败：{type(exc).__name__}: {exc}")
        return 1

    elapsed = (time.perf_counter() - started) * 1000
    content = ""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        pass
    usage = body.get("usage") or {}

    print(f"\n✓ 调用成功  耗时 {elapsed:.0f} ms")
    print(f"  模型返回：{content.strip()[:60]!r}")
    print(f"  token 用量：输入 {usage.get('prompt_tokens', '?')} / "
          f"输出 {usage.get('completion_tokens', '?')}")
    print("\n配置可用，可以接入智能体了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

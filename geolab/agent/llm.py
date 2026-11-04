# -*- coding: utf-8 -*-
"""最小的 OpenAI 兼容模型客户端（仅标准库）。

故意不引入 openai / requests：
1. 保持本项目「零第三方依赖」这条底线；
2. 只用到 chat/completions 一个接口，几十行足够；
3. 换平台（DeepSeek / 百炼 / 联通元景 / 上海智慧教育平台）只改三个环境变量。

配置来源优先级：环境变量 > 仓库根目录 .env
    GEO_API_BASE   例如 https://api.deepseek.com
    GEO_API_KEY
    GEO_MODEL      例如 deepseek-flash
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LLMError(RuntimeError):
    """调用失败。message 里带可执行的排查提示。"""


def _load_env_file() -> Dict[str, str]:
    path = os.path.join(ROOT, ".env")
    env: Dict[str, str] = {}
    if not os.path.isfile(path):
        return env
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


@dataclass
class LLMConfig:
    base: str
    key: str
    model: str
    timeout: float = 45.0

    @property
    def masked_key(self) -> str:
        if len(self.key) <= 10:
            return self.key[:2] + "*" * max(len(self.key) - 2, 0)
        return f"{self.key[:5]}…{self.key[-4:]}"


def load_config() -> Optional[LLMConfig]:
    """读不到完整配置时返回 None（调用方应回退到规则路由）。"""
    file_env = _load_env_file()

    def pick(name: str, default: str = "") -> str:
        return (os.environ.get(name) or file_env.get(name) or default).strip()

    base = pick("GEO_API_BASE", "https://api.deepseek.com").rstrip("/")
    key = pick("GEO_API_KEY")
    model = pick("GEO_MODEL", "deepseek-flash")
    if not key or not base or not model:
        return None
    return LLMConfig(base=base, key=key, model=model)


def chat_json(
    messages: List[Dict[str, str]],
    config: Optional[LLMConfig] = None,
    *,
    max_tokens: int = 600,
    timeout: float = 45.0,
    retries: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """调用模型并解析为 JSON 对象。

    返回 (数据, 元信息)。元信息含延迟与 token 用量，用于评测时算成本。
    """
    cfg = config or load_config()
    if cfg is None:
        raise LLMError("模型服务未配置：请在 .env 中填入 GEO_API_KEY")

    payload: Dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        # 路由是分类任务，不需要思维链；开着只会白烧 token 并拖慢响应
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{cfg.base}/chat/completions"

    last_error: Optional[str] = None
    for attempt in range(retries + 1):
        started = time.perf_counter()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            hint = {
                401: "key 无效", 402: "余额不足", 403: "无权限或模型未开通",
                404: "接口地址或模型名不对", 429: "触发限流",
            }.get(exc.code, "")
            last_error = f"HTTP {exc.code} {hint}：{detail}"
            if exc.code in (401, 402, 403, 404):
                raise LLMError(last_error) from exc
        except Exception as exc:  # noqa: BLE001  网络类错误可重试
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            latency = (time.perf_counter() - started) * 1000.0
            try:
                data = json.loads(raw)
                content = data["choices"][0]["message"].get("content") or ""
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = f"响应结构异常：{exc}"
                continue

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # 模型偶尔会用 ```json 包裹
                stripped = content.strip()
                if stripped.startswith("```"):
                    stripped = stripped.strip("`")
                    stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else stripped
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    last_error = f"模型未返回合法 JSON：{content[:200]!r}"
                    continue

            usage = data.get("usage") or {}
            meta = {
                "latency_ms": round(latency, 1),
                "model": cfg.model,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "attempt": attempt + 1,
            }
            return parsed, meta

        # 网络类错误：退避后重试
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))

    raise LLMError(last_error or "调用失败")

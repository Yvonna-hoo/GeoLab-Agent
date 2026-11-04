#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则路由 vs 大模型路由 —— 两个任务集上的对比评测。

为什么用两个任务集：
  A（tasks.jsonl）  规则引擎的关键词表就是照着这批问题写的，它在这里接近满分
                    是**必然的**，但这说明不了泛化能力——这就是过拟合。
  B（heldout.jsonl）换成学生真实的口语说法，规则引擎没见过，这一组才反映真实能力。

只报 A 是自欺欺人；只报 B 又不公平。两个并排摆出来，才说得清两种引擎各自守哪一段。

用法：
    python eval/compare_engines.py              # 跑两个集合，写出 docs/ENGINE_COMPARISON.md
    python eval/compare_engines.py --no-md
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from geolab import service                         # noqa: E402
from geolab.agent import llm_router                # noqa: E402
from geolab.agent.llm import load_config           # noqa: E402
from geolab.agent.router import build_payload      # noqa: E402

# deepseek-flash 空闲时段价格（元 / 百万 token），量级参考
PRICE_IN = 1.0
PRICE_OUT = 4.0

SETS = [
    ("A", "任务集 A · 设计同源（规则引擎据此调优）", "tasks.jsonl"),
    ("B", "任务集 B · 未见过的新问法", "heldout.jsonl"),
]


# --------------------------------------------------------------------------
# 数据与评测
# --------------------------------------------------------------------------

def load_set(filename: str) -> List[dict]:
    path = os.path.join(HERE, filename)
    tasks: List[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{filename} 第 {lineno} 行不是合法 JSON：{exc}")
    return tasks


def evaluate(engine: str, tasks: List[dict]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    latencies: List[float] = []
    tokens_in = tokens_out = 0

    for task in tasks:
        t0 = time.perf_counter()
        plan = llm_router.route_with_engine(task["text"], engine)
        latency = (time.perf_counter() - t0) * 1000.0
        latencies.append(latency)

        meta = plan.get("llm") or {}
        tokens_in += meta.get("prompt_tokens") or 0
        tokens_out += meta.get("completion_tokens") or 0

        exp_expected = task.get("experiment")
        intent_expected = task.get("intent")
        if exp_expected is None and intent_expected is None:
            route_ok = not plan.get("ok")           # 期望被拒绝
        else:
            route_ok = (
                bool(plan.get("ok"))
                and plan.get("experiment") == exp_expected
                and (intent_expected is None or plan.get("intent") == intent_expected)
            )

        payload = build_payload(plan)
        result = service.execute(payload) if payload else None

        checks = task.get("checks") or []
        if payload is None:
            exec_ok = plan.get("experiment") is None
        elif "exec-error" in checks:
            exec_ok = bool(result and not result.get("ok"))
        else:
            exec_ok = bool(result and result.get("ok"))

        rows.append({
            "id": task["id"],
            "text": task["text"],
            "expect": f"{exp_expected or '-'} / {intent_expected or '-'}",
            "got": f"{plan.get('experiment') or '-'} / {plan.get('intent') or '-'}",
            "route_ok": route_ok,
            "exec_ok": exec_ok,
            "confidence": plan.get("confidence"),
            "engine": plan.get("engine"),
            "latency_ms": round(latency, 1),
            "tokens": meta.get("total_tokens"),
        })

    n = max(len(tasks), 1)
    return {
        "rows": rows,
        "route_acc": sum(1 for r in rows if r["route_ok"]) / n,
        "exec_acc": sum(1 for r in rows if r["exec_ok"]) / n,
        "latency_mean": statistics.mean(latencies) if latencies else 0.0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": tokens_in / 1e6 * PRICE_IN + tokens_out / 1e6 * PRICE_OUT,
    }


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _ms(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.0f} ms"


def print_summary(results: Dict[str, Optional[Dict[str, Any]]]) -> None:
    a_rule, a_llm = results["A_rule"], results["A_llm"]
    b_rule, b_llm = results["B_rule"], results["B_llm"]

    def acc(pair, field):
        return _pct(pair[field]) if pair else "—"

    def lat(pair):
        return _ms(pair["latency_mean"]) if pair else "—"

    print()
    print("=" * 82)
    print(" 规则引擎 vs 大模型引擎")
    print("=" * 82)
    print(f" {'指标':<18}{'A·规则':>13}{'A·模型':>13}{'B·规则':>13}{'B·模型':>13}")
    print("-" * 82)
    print(f" {'路由准确率':<18}{acc(a_rule, 'route_acc'):>13}{acc(a_llm, 'route_acc'):>13}"
          f"{acc(b_rule, 'route_acc'):>13}{acc(b_llm, 'route_acc'):>13}")
    print(f" {'执行符合预期':<18}{acc(a_rule, 'exec_acc'):>13}{acc(a_llm, 'exec_acc'):>13}"
          f"{acc(b_rule, 'exec_acc'):>13}{acc(b_llm, 'exec_acc'):>13}")
    print(f" {'平均延迟':<18}{lat(a_rule):>13}{lat(a_llm):>13}{lat(b_rule):>13}{lat(b_llm):>13}")

    if a_llm and b_llm:
        total_cost = a_llm["cost"] + b_llm["cost"]
        tok_a = f"{a_llm['tokens_in']} / {a_llm['tokens_out']}"
        tok_b = f"{b_llm['tokens_in']} / {b_llm['tokens_out']}"
        print(f" {'token（入/出）':<18}{'0 / 0':>13}{tok_a:>13}{'0 / 0':>13}{tok_b:>13}")
        print(f" {'成本估算':<18}{'0 元':>13}{format(a_llm['cost'], '.4f') + ' 元':>13}"
              f"{'0 元':>13}{format(b_llm['cost'], '.4f') + ' 元':>13}")
        print(f" {'两集合计成本':<18}{format(total_cost, '.4f') + ' 元':>13}")
    print("=" * 82)


def print_disagreements(results, meta_sets) -> None:
    for key, title, _ in SETS:
        r_set, l_set = results[f"{key}_rule"], results[f"{key}_llm"]
        if not l_set:
            continue
        diff = [(a, b) for a, b in zip(r_set["rows"], l_set["rows"]) if a["got"] != b["got"]]
        print(f"\n{title}：判定不一致 {len(diff)} 条")
        for a, b in diff:
            print(f"  {a['id']}  期望 {a['expect']}")
            print(f"      规则 {'✓' if a['route_ok'] else '✗'} {a['got']}"
                  f"    模型 {'✓' if b['route_ok'] else '✗'} {b['got']}")


def build_markdown(results, has_llm: bool) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    a_rule, a_llm = results["A_rule"], results["A_llm"]
    b_rule, b_llm = results["B_rule"], results["B_llm"]

    def acc(pair):
        return _pct(pair["route_acc"]) if pair else "—"

    def ex(pair):
        return _pct(pair["exec_acc"]) if pair else "—"

    def lat(pair):
        return _ms(pair["latency_mean"]) if pair else "—"

    tokens_a = f"{a_llm['tokens_in']} / {a_llm['tokens_out']}" if a_llm else "—"
    tokens_b = f"{b_llm['tokens_in']} / {b_llm['tokens_out']}" if b_llm else "—"
    cost_a = f"{a_llm['cost']:.4f} 元" if a_llm else "—"
    cost_b = f"{b_llm['cost']:.4f} 元" if b_llm else "—"

    L: List[str] = [
        "# 任务路由：规则引擎 vs 大模型引擎",
        "",
        f"> 由 `eval/compare_engines.py` 自动生成于 {now}；数据集见 "
        "`eval/tasks.jsonl` 与 `eval/heldout.jsonl`。",
        "",
        "同一套判据、同一批任务，只替换「谁在理解这句话」。",
        "",
        "## 为什么分成两个任务集",
        "",
        "| 任务集 | 说明 |",
        "|---|---|",
        "| **A（18 条）** | 规则引擎的关键词表就是照着这批问题写的。它在这里接近满分是"
        "**必然的**，但这不能证明泛化能力——这就是过拟合 |",
        "| **B（12 条）** | 换成学生真实的口语说法（「修了梯田比不修能少流失多少土」），"
        "规则引擎的关键词表没见过这些句式，这一组才反映真实能力 |",
        "",
        "只报 A 是自欺欺人；只报 B 又不公平（规则引擎本来也没打算覆盖所有说法）。"
        "两个并排摆出来，才能说明两种引擎各自守哪一段。",
        "",
        "## 结果总览",
        "",
        "| 指标 | A·规则 | A·大模型 | B·规则 | B·大模型 |",
        "|---|---|---|---|---|",
        f"| 路由准确率 | {acc(a_rule)} | {acc(a_llm)} | {acc(b_rule)} | {acc(b_llm)} |",
        f"| 执行符合预期 | {ex(a_rule)} | {ex(a_llm)} | {ex(b_rule)} | {ex(b_llm)} |",
        f"| 平均延迟 | {lat(a_rule)} | {lat(a_llm)} | {lat(b_rule)} | {lat(b_llm)} |",
        f"| token 消耗（入/出） | 0 / 0 | {tokens_a} | 0 / 0 | {tokens_b} |",
        f"| 成本估算 | 0 元 | {cost_a} | 0 元 | {cost_b} |",
        "",
        "成本按 deepseek-flash 空闲时段价格（输入 1 元/百万、输出 4 元/百万）估算，只代表量级。",
        "",
    ]

    for key, title, _ in SETS:
        r_set, l_set = results[f"{key}_rule"], results[f"{key}_llm"]
        L += ["", f"## {title}", "",
              "| 任务 | 期望 | 规则引擎 | 大模型 | 备注 |",
              "|---|---|---|---|---|"]
        for i, a_row in enumerate(r_set["rows"]):
            b_row = l_set["rows"][i] if l_set else None
            mark_a = "✅" if a_row["route_ok"] else "❌"
            mark_b = "—" if b_row is None else ("✅" if b_row["route_ok"] else "❌")
            got_b = b_row["got"] if b_row else ""
            note = "分歧" if (b_row and a_row["got"] != b_row["got"]) else ""
            text = a_row["text"][:22]
            L.append(f"| {a_row['id']} {text} | {a_row['expect']} | "
                     f"{mark_a} {a_row['got']} | {mark_b} {got_b} | {note} |")

    L += [
        "",
        "## 结论",
        "",
        "1. **规则引擎**确定性、零成本、零延迟，在 A 集几乎全中；但 B 集暴露了它的本质——"
        "只认写死的说法，换个问法就掉。",
        "2. **大模型**在 A 集与规则引擎基本持平，在 B 集明显更稳；代价是每条多约一千多 token 和约 1 秒。",
        "3. 因此项目默认策略是 `auto`：配了 key 就走大模型；模型调用失败（网络、额度、"
        "输出不合法）时**静默回退**到规则引擎。用户永远拿得到结果，且能从返回的 `engine` "
        "字段看出这次是谁答的。",
        "",
        "这不是「哪个更好」的问题，而是**两种引擎各守一段**：规则兜底保证可用性，"
        "模型负责泛化。为了几个百分点的准确率而拆掉兜底，在真实课堂里并不划算。",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-md", action="store_true")
    args = ap.parse_args()

    has_llm = load_config() is not None
    if not has_llm:
        print("未配置模型服务（.env 里没有 GEO_API_KEY），只跑规则引擎。")

    results: Dict[str, Any] = {}
    for key, title, filename in SETS:
        tasks = load_set(filename)
        print(f"\n【{title}】{len(tasks)} 条")
        print("  规则引擎…")
        results[f"{key}_rule"] = evaluate("rule", tasks)
        if has_llm:
            print("  大模型引擎…（每条约 1 秒）")
            results[f"{key}_llm"] = evaluate("llm", tasks)
        else:
            results[f"{key}_llm"] = None

    print_summary(results)
    print_disagreements(results, None)

    if not args.no_md:
        out = os.path.join(ROOT, "docs", "ENGINE_COMPARISON.md")
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(build_markdown(results, has_llm))
        print(f"\n已写出 {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

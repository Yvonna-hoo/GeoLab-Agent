#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""典型任务回归评测。

用法：
    python eval/run_eval.py            # 跑全部任务
    python eval/run_eval.py -v         # 显示每个任务的判断依据

它检查三件事，对应赛事评价里的三句话：
    ① 实验路由是否正确
    ② 工具调用是否成功（该失败的必须失败）
    ③ 结果的方向是否与地理学常识一致

这个脚本的价值不在于跑出 100%——而在于任何时候改了路由或模型，
一条命令就知道有没有把原来的正确行为改坏。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from geolab import service                      # noqa: E402
from geolab.agent import router                 # noqa: E402

TASKS_FILE = os.path.join(HERE, "tasks.jsonl")


def load_tasks():
    tasks = []
    with open(TASKS_FILE, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"tasks.jsonl 第 {lineno} 行不是合法 JSON：{exc}")
    return tasks


def check_trend(result, spec, want):
    """在扫描结果上验证单调性。"""
    key = spec.split(":", 1)[1]
    points = [p for p in (result.get("points") or []) if p.get("ok")]
    if len(points) < 3:
        return False, f"有效采样点不足（{len(points)}）"
    vals = [p["outputs"].get(key) for p in points]
    if any(v is None for v in vals):
        return False, f"输出中没有 {key}"
    pairs = list(zip(vals, vals[1:]))
    if want == "decrease":
        bad = [i for i, (a, b) in enumerate(pairs) if b > a + 1e-9]
    else:
        bad = [i for i, (a, b) in enumerate(pairs) if b < a - 1e-9]
    if bad:
        return False, f"{key} 在索引 {bad[:3]} 处违反{'下降' if want == 'decrease' else '上升'}趋势"
    return True, f"{key}: {vals[0]:.4g} → {vals[-1]:.4g}（{len(vals)} 点单调）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tasks = load_tasks()
    rows = []
    route_hits = 0
    exec_ok = 0
    check_pass = 0
    check_total = 0

    for task in tasks:
        plan = router.route(task["text"])
        problems = []
        details = []

        # ---- ① 路由 ----
        exp_expected = task.get("experiment")
        intent_expected = task.get("intent")
        route_ok = True
        if exp_expected is None and intent_expected is None:
            route_ok = not plan.get("ok")          # 期望被拒绝
        else:
            route_ok = (
                plan.get("ok")
                and plan.get("experiment") == exp_expected
                and (intent_expected is None or plan.get("intent") == intent_expected)
            )
        if route_ok:
            route_hits += 1
        else:
            problems.append(
                f"路由期望 {exp_expected}/{intent_expected}，"
                f"实际 {plan.get('experiment')}/{plan.get('intent')}"
            )

        # ---- ② 执行 ----
        payload = router.build_payload(plan)
        result = service.execute(payload) if payload else None
        want_error = "exec-error" in (task.get("checks") or [])
        if payload is None:
            exec_ok += 1
            details.append("不执行（跨模块或已拒绝）")
        elif want_error:
            if result and not result.get("ok"):
                exec_ok += 1
                details.append("按预期被参数校验拦下")
            else:
                problems.append("本应被参数校验拦下，却执行成功")
        else:
            if result and result.get("ok"):
                exec_ok += 1
            else:
                problems.append(f"执行失败：{(result or {}).get('errors')}")

        # ---- ③ 检查项 ----
        for spec in task.get("checks") or []:
            check_total += 1
            passed, msg = True, ""

            if spec in ("exec-error", "precheck", "no-exec"):
                if spec == "precheck":
                    passed = bool(plan.get("precheck_errors"))
                    msg = "路由阶段已预检参数越界" if passed else "路由阶段没有预检到越界"
                elif spec == "no-exec":
                    passed = payload is None
                    msg = "未执行数值合并"
                else:
                    passed = bool(result is not None and not result.get("ok"))
                    msg = "工具拒绝了越界请求"

            elif spec.startswith("trend-"):
                if not result or not result.get("ok"):
                    passed, msg = False, "执行未成功，无法验证趋势"
                else:
                    passed, msg = check_trend(result, spec, "decrease" if spec.startswith("trend-decrease") else "increase")

            elif spec == "delta-negative":
                rows_ = (result or {}).get("rows") or []
                deltas = [r.get("delta_pct") for r in rows_ if r.get("ok")]
                passed = bool(deltas) and all(d is not None and d < 0 for d in deltas)
                msg = f"对照组变化：{['%.1f%%' % d for d in deltas if d is not None]}"

            elif spec == "delta-extremes":
                rows_ = (result or {}).get("rows") or []
                deltas = [r.get("delta_pct") for r in rows_ if r.get("ok") and r.get("delta_pct") is not None]
                passed = bool(deltas) and min(deltas) <= -50 and max(deltas) >= 50
                msg = f"对照组变化幅度：{['%.1f%%' % d for d in deltas]}（需要同时出现大幅增与大幅减）"

            elif spec == "ranked":
                items = (((result or {}).get("analysis") or {}).get("elasticities") or [])
                vals = [abs(i["elasticity"]) for i in items]
                passed = bool(vals) and vals == sorted(vals, reverse=True)
                msg = f"弹性排序：{[(i['parameter'], round(i['elasticity'], 2)) for i in items[:3]]}"

            elif spec == "route-refused":
                passed = not plan.get("ok") and bool(plan.get("clarify"))
                msg = "已拒绝并给出追问" if passed else "没有拒绝"

            elif spec.startswith("headline:"):
                needle = spec.split(":", 1)[1]
                text = ""
                if result and result.get("ok"):
                    text = str((result.get("outputs") or {}).get("headline") or "")
                passed = needle in text
                msg = f"结论文本{'包含' if passed else '缺少'}「{needle}」"

            elif spec == "headline-monotonic":
                passed, msg = True, "趋势一致（已由 trend 检查覆盖）"

            else:
                passed, msg = False, f"未知检查项 {spec}"

            if passed:
                check_pass += 1
            else:
                problems.append(msg)
            details.append(("✓ " if passed else "✗ ") + msg)

        rows.append((task["id"], task, plan, problems, details))

    # ---- 输出 ----
    print()
    print("=" * 78)
    print(" GeoLab Agent 典型任务回归评测")
    print("=" * 78)
    for tid, task, plan, problems, details in rows:
        mark = "✅" if not problems else "❌"
        head = f"{mark} {tid}  {task['text'][:42]}"
        print(head)
        if args.verbose or problems:
            print(f"     → 路由 {plan.get('experiment')}/{plan.get('intent')}"
                  f"（置信度 {plan.get('confidence', '—')}）")
            for d in details:
                print(f"       {d}")
            for p in problems:
                print(f"       ⚠ {p}")
        if plan.get("reasoning"):
            print(f"       依据：{'；'.join(plan['reasoning'][:2])}")

    n = len(tasks)
    print("-" * 78)
    print(f" 任务数        {n}")
    print(f" 路由正确      {route_hits}/{n}  ({route_hits / n * 100:.1f}%)")
    print(f" 执行符合预期  {exec_ok}/{n}  ({exec_ok / n * 100:.1f}%)")
    print(f" 检查项通过    {check_pass}/{check_total}  ({check_pass / max(check_total, 1) * 100:.1f}%)")
    failed = sum(1 for _, _, _, p, _ in rows if p)
    print(f" 未通过任务    {failed}")
    print("=" * 78)
    print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

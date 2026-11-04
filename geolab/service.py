# -*- coding: utf-8 -*-
"""服务层：把「一个实验」扩展成四种可执行的探究模式。

    run      单次计算
    sweep    单参数扫描（做对照曲线）
    compare  基准 vs 若干对照组（做对照表）
    analyze  数值敏感性（弹性系数），回答「改哪个因子最有效」

模式逻辑全部写在这里，实验子类因此只需要实现纯计算，天然保持可复用。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .protocol import (
    Experiment,
    envelope,
    failure,
    make_error,
    numeric_elasticity,
)
from .registry import REGISTRY, catalog, get

MODES = ("run", "sweep", "compare", "analyze")
MAX_SWEEP_POINTS = 200
MAX_COMPARE_VARIANTS = 12


def _primary_key(exp: Experiment) -> str:
    key = getattr(exp, "primary_output", "") or ""
    if key:
        return key
    return exp.outputs[0]["key"] if exp.outputs else ""


def execute(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    started = time.perf_counter()
    payload = payload or {}

    exp_id = payload.get("experiment")
    exp = get(exp_id) if exp_id else None
    if exp is None:
        return {
            "ok": False,
            "errors": [make_error(
                "experiment", "unknown_experiment",
                f"未知实验 {exp_id!r}；可用实验：{sorted(REGISTRY)}",
                allowed=sorted(REGISTRY),
            )],
        }

    mode = (payload.get("mode") or "run").strip()
    if mode not in MODES:
        return {
            "ok": False,
            "errors": [make_error(
                "mode", "unknown_mode",
                f"不支持的执行模式 {mode!r}；可用模式：{list(MODES)}",
                allowed=list(MODES),
            )],
            "experiment": {"id": exp.id, "title": exp.title},
        }

    base_params, errors = exp.validate(payload.get("params"))
    if errors:
        return failure(errors, exp, started)

    if mode == "run":
        return _run(exp, base_params, started)
    if mode == "sweep":
        return _sweep(exp, base_params, payload.get("sweep") or {}, started)
    if mode == "compare":
        return _compare(exp, base_params, payload.get("compare") or {}, started)
    return _analyze(exp, base_params, payload.get("analyze") or {}, started)


# --------------------------------------------------------------------------
# 四种模式
# --------------------------------------------------------------------------

def _run(exp: Experiment, params: Dict[str, Any], started: float) -> Dict[str, Any]:
    outputs = exp.run(params)
    return envelope(exp, "run", params, outputs, started)


def _sweep(exp: Experiment, base: Dict[str, Any], spec: Dict[str, Any],
           started: float) -> Dict[str, Any]:
    parameter = spec.get("parameter")
    p = exp.param(parameter) if parameter else None
    if p is None:
        return failure([make_error(
            "sweep.parameter", "unknown_parameter",
            f"扫描参数 {parameter!r} 不存在；可用参数：{sorted(q.name for q in exp.parameters)}",
            allowed=[q.name for q in exp.parameters],
        )], exp, started)

    values = _resolve_values(p, spec)
    if isinstance(values, dict) and "error" in values:
        return failure([values["error"]], exp, started)
    if len(values) > MAX_SWEEP_POINTS:
        return failure([make_error(
            "sweep.values", "too_many_points",
            f"扫描点最多 {MAX_SWEEP_POINTS} 个，当前 {len(values)} 个",
            allowed={"max_points": MAX_SWEEP_POINTS},
        )], exp, started)

    points: List[Dict[str, Any]] = []
    series_map: Dict[str, List] = {}

    for value in values:
        probe = dict(base)
        probe[parameter] = value
        point_params, errs = exp.validate(probe)
        if errs:
            points.append({
                "value": value,
                "ok": False,
                "errors": errs,
            })
            continue
        try:
            out = exp.run(point_params)
        except Exception as exc:  # 单个点失败不应毁掉整条曲线
            points.append({"value": value, "ok": False,
                           "errors": [make_error(parameter, "compute_failed", str(exc))]})
            continue
        points.append({"value": value, "ok": True, "outputs": out})
        for key, val in out.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                series_map.setdefault(key, []).append([value, float(val)])

    series = []
    for key, pts in series_map.items():
        if len(pts) < 2:
            continue
        series.append({
            "key": key,
            "label": _output_label(exp, key),
            "points": pts,
        })

    extra = {
        "sweep": {
            "parameter": parameter,
            "label": p.label,
            "unit": p.unit,
            "values": values,
        },
        "points": points,
        "series": series,
        "primary_output": _primary_key(exp),
        "primary_label": _output_label(exp, _primary_key(exp)),
    }
    return envelope(exp, "sweep", base, {"points_count": len(points)}, started, extra)


def _compare(exp: Experiment, base: Dict[str, Any], spec: Dict[str, Any],
             started: float) -> Dict[str, Any]:
    variants = spec.get("variants") or []
    if not isinstance(variants, list) or not variants:
        return failure([make_error(
            "compare.variants", "required",
            "对照模式需要提供 variants 数组，例如 [{\"label\":\"覆盖度 20%\",\"params\":{\"vegetation_cover_pct\":20}}]",
        )], exp, started)
    if len(variants) > MAX_COMPARE_VARIANTS:
        return failure([make_error(
            "compare.variants", "too_many_variants",
            f"对照组最多 {MAX_COMPARE_VARIANTS} 组，当前 {len(variants)} 组",
        )], exp, started)

    base_out = exp.run(base)
    pk = _primary_key(exp)
    base_val = base_out.get(pk)

    rows: List[Dict[str, Any]] = []
    for idx, variant in enumerate(variants):
        label = (variant or {}).get("label") or f"对照组 {idx + 1}"
        override = (variant or {}).get("params") or {}
        merged = dict(base)
        merged.update(override)
        params, errs = exp.validate(merged)
        if errs:
            rows.append({"label": label, "ok": False, "errors": errs, "overrides": override})
            continue
        out = exp.run(params)
        val = out.get(pk)
        delta = None
        if isinstance(val, (int, float)) and isinstance(base_val, (int, float)) and base_val:
            delta = (val - base_val) / abs(base_val) * 100.0
        rows.append({
            "label": label,
            "ok": True,
            "overrides": override,
            "params": params,
            "outputs": out,
            "primary": val,
            "delta_pct": round(delta, 2) if delta is not None else None,
        })

    extra = {
        "compare": {
            "baseline_label": spec.get("baseline_label") or "基准组",
            "primary_key": pk,
            "primary_label": _output_label(exp, pk),
        },
        "baseline": {"params": base, "outputs": base_out},
        "rows": rows,
    }
    return envelope(exp, "compare", base, {"rows_count": len(rows)}, started, extra)


def _analyze(exp: Experiment, base: Dict[str, Any], spec: Dict[str, Any],
             started: float) -> Dict[str, Any]:
    keys = spec.get("outputs") or [_primary_key(exp)]
    items: List[Dict[str, Any]] = []
    for p in exp.parameters:
        if p.kind != "number" or p.optional:
            continue
        items.extend(numeric_elasticity(exp, base, p.name, keys))

    items.sort(key=lambda d: abs(d["elasticity"]), reverse=True)
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank

    pk = keys[0] if keys else ""
    extra = {
        "primary_output": pk,
        "primary_label": _output_label(exp, pk),
        "analysis": {
            "outputs": keys,
            "elasticities": items,
            "reading": (
                "弹性系数 = d(ln输出)/d(ln参数)。绝对值越大，说明该参数变化 1% 对结果影响越大；"
                "正号表示同向，负号表示反向。数值由中心差分估算，不依赖解析求导。"
            ),
        },
    }
    return envelope(exp, "analyze", base, {"count": len(items)}, started, extra)


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def _output_label(exp: Experiment, key: str) -> str:
    for item in exp.outputs:
        if item["key"] == key:
            unit = item.get("unit") or ""
            return f"{item['label']}" + (f"（{unit}）" if unit else "")
    return key


def _resolve_values(p, spec: Dict[str, Any]):
    """把扫描规格解析成值列表：支持显式 values，也支持 start/stop/steps。"""
    if spec.get("values"):
        raw = list(spec["values"])
    elif spec.get("start") is not None and spec.get("stop") is not None:
        steps = int(spec.get("steps") or 20)
        if steps < 2 or steps > MAX_SWEEP_POINTS:
            return {"error": make_error(
                "sweep.steps", "bad_steps",
                f"扫描步数需在 2~{MAX_SWEEP_POINTS} 之间，当前 {steps}",
            )}
        start = float(spec["start"])
        stop = float(spec["stop"])
        if start == stop:
            return {"error": make_error("sweep", "empty_range", "扫描起止值相同")}
        step = (stop - start) / (steps - 1)
        raw = [start + step * i for i in range(steps)]
    elif p.choices:
        raw = [c["value"] for c in p.choices]
    elif p.minimum is not None and p.maximum is not None:
        # 既没给 values 也没给 start/stop：按参数自身量程自动生成 10 个点
        steps = 10
        step = (p.maximum - p.minimum) / (steps - 1)
        raw = [p.minimum + step * i for i in range(steps)]
    else:
        return {"error": make_error(
            "sweep", "need_values",
            "扫描模式需要 values 数组，或 start/stop/steps",
        )}

    # 规范化：枚举保持字符串，数值转 float
    if p.kind == "enum":
        return raw
    out = []
    for v in raw:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            return {"error": make_error(
                "sweep.values", "not_a_number",
                f"扫描值 {v!r} 不是数值",
            )}
    return out

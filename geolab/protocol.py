# -*- coding: utf-8 -*-
"""GeoLab 统一实验协议。

设计目标（直接对应赛事评分点「新增实验模块的复用能力」）：

1. 实验只用**声明式**方式描述参数，新增实验不需要改前端、服务器或智能体代码；
2. 校验错误是结构化的，便于大模型读取后**自我修正**再重试；
3. 结果封装统一携带单位、假设与适用范围，便于人工核查「AI 解释是否忠实于工具输出」。

协议只依赖 Python 标准库。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ENGINE = "geolab-core"
ENGINE_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# 结构化错误
# --------------------------------------------------------------------------

def make_error(field_name: str, code: str, message: str, **extra: Any) -> Dict[str, Any]:
    """构造一条可被程序消费、也可被人读懂的错误。"""
    item: Dict[str, Any] = {"field": field_name, "code": code, "message": message}
    item.update(extra)
    return item


# --------------------------------------------------------------------------
# 参数声明
# --------------------------------------------------------------------------

@dataclass
class Param:
    """一个实验参数的声明。

    kind: number | enum | bool
    """

    name: str
    label: str
    kind: str = "number"
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    default: Any = None
    choices: Optional[List[Dict[str, Any]]] = None
    description: str = ""
    optional: bool = False
    step: Optional[float] = None
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "unit": self.unit,
            "default": self.default,
            "description": self.description,
            "optional": self.optional,
        }
        if self.minimum is not None:
            out["min"] = self.minimum
        if self.maximum is not None:
            out["max"] = self.maximum
        if self.choices is not None:
            out["choices"] = self.choices
        if self.step is not None:
            out["step"] = self.step
        if self.source:
            out["source"] = self.source
        return out

    def coerce(self, raw: Any) -> Tuple[Any, List[Dict[str, Any]]]:
        """把外部输入转成规范值；返回 (值, 错误列表)。"""
        errors: List[Dict[str, Any]] = []

        if raw is None:
            if self.optional:
                return None, []
            if self.default is None:
                return None, [make_error(self.name, "required", f"缺少必填参数「{self.label}」")]
            return self.default, []

        if self.kind == "number":
            if isinstance(raw, bool):
                return None, [make_error(self.name, "not_a_number", f"「{self.label}」必须是数值，不能是布尔值")]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return None, [make_error(
                    self.name, "not_a_number",
                    f"「{self.label}」必须是数值，收到 {raw!r}；允许范围 "
                    f"{self.minimum}~{self.maximum}{self.unit}",
                )]
            if not math.isfinite(value):
                return None, [make_error(self.name, "not_finite", f"「{self.label}」必须是有限数值")]
            if self.minimum is not None and value < self.minimum - 1e-12:
                errors.append(make_error(
                    self.name, "below_min",
                    f"「{self.label}」不能小于 {self.minimum}{self.unit}，收到 {value:g}",
                    allowed={"min": self.minimum, "max": self.maximum, "unit": self.unit},
                ))
            if self.maximum is not None and value > self.maximum + 1e-12:
                errors.append(make_error(
                    self.name, "above_max",
                    f"「{self.label}」不能大于 {self.maximum}{self.unit}，收到 {value:g}",
                    allowed={"min": self.minimum, "max": self.maximum, "unit": self.unit},
                ))
            return value, errors

        if self.kind == "enum":
            allowed = [c["value"] for c in (self.choices or [])]
            if raw not in allowed:
                labels = "、".join(f"{c['value']}（{c['label']}）" for c in (self.choices or []))
                return None, [make_error(
                    self.name, "bad_choice",
                    f"「{self.label}」只能取：{labels}；收到 {raw!r}",
                    allowed=allowed,
                )]
            return raw, errors

        if self.kind == "bool":
            if isinstance(raw, bool):
                return raw, []
            if isinstance(raw, str):
                return raw.strip().lower() in ("true", "1", "yes", "y"), []
            return bool(raw), []

        return None, [make_error(self.name, "unknown_kind", f"参数「{self.name}」类型 {self.kind} 不受支持")]


# --------------------------------------------------------------------------
# 实验基类
# --------------------------------------------------------------------------

class Experiment:
    """所有地理实验的公共基类。

    子类只需要：
      - 提供元信息（id / title / summary / parameters / assumptions / limitations / outputs）
      - 实现 run(params) -> dict，返回纯数值结果
    模式（单次 / 扫描 / 对照 / 敏感性）由服务层统一处理，不在子类里重复。
    """

    id: str = ""
    title: str = ""
    summary: str = ""
    version: str = "1.0.0"
    domain: str = "地理科学"
    parameters: List[Param] = []
    assumptions: List[str] = []
    limitations: List[str] = []
    outputs: List[Dict[str, str]] = []
    keywords: List[str] = []
    # 主输出：对照表、敏感性分析和图表默认盯着的那个指标
    primary_output: str = ""

    # ---- 元信息 ----

    def describe(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "version": self.version,
            "domain": self.domain,
            "parameters": [p.to_dict() for p in self.parameters],
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "outputs": list(self.outputs),
            "keywords": list(self.keywords),
        }

    def param(self, name: str) -> Optional[Param]:
        for p in self.parameters:
            if p.name == name:
                return p
        return None

    # ---- 校验 ----

    def validate(self, raw: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """校验并规范化参数。未知参数会被拒绝（避免用户以为参数生效了）。"""
        raw = dict(raw or {})
        errors: List[Dict[str, Any]] = []
        clean: Dict[str, Any] = {}

        known = {p.name for p in self.parameters}
        for key in raw:
            if key not in known:
                errors.append(make_error(
                    key, "unknown_parameter",
                    f"实验「{self.title}」没有参数 {key}；可用参数：{sorted(known)}",
                    allowed=sorted(known),
                ))

        for p in self.parameters:
            value, errs = p.coerce(raw.get(p.name))
            errors.extend(errs)
            if not errs:
                clean[p.name] = value

        if not errors:
            errors.extend(self.check(clean))
        return clean, errors

    def check(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """跨参数的一致性校验，子类可覆盖。"""
        return []

    # ---- 计算 ----

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


# --------------------------------------------------------------------------
# 结果封装
# --------------------------------------------------------------------------

def envelope(
    experiment: Experiment,
    mode: str,
    params: Dict[str, Any],
    outputs: Dict[str, Any],
    started: float,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """统一的成功响应。assumptions/limitations 每次都随结果返回，
    保证任何下游（人、报告、大模型）都能看到同样的边界说明。"""
    body: Dict[str, Any] = {
        "ok": True,
        "experiment": {
            "id": experiment.id,
            "title": experiment.title,
            "version": experiment.version,
            "domain": experiment.domain,
        },
        "mode": mode,
        "params": params,
        "outputs": outputs,
        "assumptions": list(experiment.assumptions),
        "limitations": list(experiment.limitations),
        "trace": {
            "engine": ENGINE,
            "engine_version": ENGINE_VERSION,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
        },
    }
    if extra:
        body.update(extra)
    return body


def failure(errors: List[Dict[str, Any]], experiment: Optional[Experiment] = None,
            started: Optional[float] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"ok": False, "errors": errors}
    if experiment is not None:
        body["experiment"] = {"id": experiment.id, "title": experiment.title}
        body["assumptions"] = list(experiment.assumptions)
        body["limitations"] = list(experiment.limitations)
    if started is not None:
        body["trace"] = {
            "engine": ENGINE,
            "engine_version": ENGINE_VERSION,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
    return body


def numeric_elasticity(experiment: Experiment, params: Dict[str, Any],
                       parameter: str, keys: List[str]) -> List[Dict[str, Any]]:
    """数值弹性系数 d(lnY)/d(lnX)：衡量「把哪个因子改 1% 最有效」。

    用中心差分实现，不假设模型可解析求导，因此对任何实验都适用。
    """
    base = experiment.run(params)
    results: List[Dict[str, Any]] = []
    p = experiment.param(parameter)
    if p is None or p.kind != "number":
        return results

    x0 = params.get(parameter)
    if not x0:
        return results
    # 步长取 1%，而不是更小的 0.1%：输出值本身只保留三位小数，
    # 步长过小时差值会被舍入误差淹没，弹性系数反而算不准。
    h = max(abs(x0) * 1e-2, 1e-9)

    lo = dict(params); lo[parameter] = x0 - h
    hi = dict(params); hi[parameter] = x0 + h
    if p.minimum is not None and lo[parameter] < p.minimum:
        lo[parameter] = p.minimum
    if p.maximum is not None and hi[parameter] > p.maximum:
        hi[parameter] = p.maximum

    try:
        out_lo = experiment.run(lo)
        out_hi = experiment.run(hi)
    except Exception:
        return results

    for key in keys:
        y0 = base.get(key)
        y_lo = out_lo.get(key)
        y_hi = out_hi.get(key)
        if y0 is None or y_lo is None or y_hi is None:
            continue
        x_lo = lo[parameter]
        x_hi = hi[parameter]
        if y0 <= 0 or y_lo <= 0 or y_hi <= 0 or x_lo <= 0 or x_hi <= 0:
            continue
        dlny = math.log(y_hi) - math.log(y_lo)
        dlnx = math.log(x_hi) - math.log(x_lo)
        if abs(dlnx) < 1e-15:
            continue
        results.append({
            "output": key,
            "parameter": parameter,
            "label": p.label,
            "value": x0,
            "elasticity": round(dlny / dlnx, 4),
            "reading": "1% 变化引起约 {:.2f}% 变化".format(dlny / dlnx),
        })
    return results

# -*- coding: utf-8 -*-
"""大模型任务路由。

与规则路由 router.py 输出**完全相同**的结构，因此下游（service、前端、评测）
一行都不用改。两者的差别只在「谁来理解这句话」。

设计上的三个约束：
1. 提示词里的实验与参数清单是从 registry **动态生成**的，新增实验不用改提示词；
2. 模型给出的实验名、参数名、模式都会再校验一遍，不合法的直接回退规则路由；
3. 任何失败（网络、额度、JSON 坏掉）都不抛给用户，静默回退并在结果里标明来源。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..registry import REGISTRY
from . import router as rule_router
from .llm import LLMConfig, LLMError, chat_json, load_config

VALID_MODES = ("run", "sweep", "compare", "analyze")

MODE_DEFS = """
- run      单点估算：想知道「大概多少 / 有多严重 / 属什么等级」
- sweep    单因子关系：想知道「随着 X 变化 Y 会怎样 / 是不是线性 / 趋势」
- compare  方案比较：想知道「哪个方案更好 / 改成 X 之后能减少多少 / 做对照」
- analyze  因子重要性：想知道「哪个因子影响最大 / 谁最敏感 / 主要原因是哪个」
""".strip()

SYSTEM_TMPL = """你是「GeoLab Agent」的任务路由器，负责把一个地理探究问题翻译成可执行的实验方案。

# 可用实验与参数

{catalog}

# 模式定义

{mode_defs}

# 输出要求

只输出一个 JSON 对象，不要任何解释文字，字段如下：

{{
  "experiment": "实验 id，或 null（无法执行时）",
  "intent": "run | sweep | compare | analyze | cross_module",
  "params": {{ "参数名": 数值或字符串 }},
  "sweep_parameter": "当 intent=sweep 时的自变量参数名，否则 null",
  "compare_variants": [{{"label": "方案名", "params": {{"参数名": 值}}}}] 或 null,
  "reason": "一句话说明判断依据",
  "confidence": 0.0 到 1.0 之间的小数
}}

# 硬性规则

1. 参数名必须来自上面的清单，**不要自造参数名**（例如没有 vegetation_cover，只有 vegetation_cover_pct）。
2. params 只需要写问题里明确或暗示要改的参数，其余留空即可，系统会用默认值补齐。
3. 数值不要超出清单给出的范围；如果用户给的值明显不合理（例如覆盖度 130%），
   **照原样填进去**，让工具去拒绝它，不要自己改成合理值。
4. 与两个实验都无关的问题（闲聊、写诗、其他学科），experiment 返回 null。
5. 问题同时牵涉**坡面产沙**与**河道冲淤**，且问的是两者的关系或因果链时，
   intent 返回 "cross_module"、experiment 返回 null（这类问题只能做概念串联，不能合并数值）。
6. compare_variants 里**只放与基准不同的方案**。基准组会由 params 自动承担，
   不要把「无措施/不修」这种基准本身再写成一个对照。

# 示例

问题：在其他条件不变时，植被覆盖变化会怎样影响土壤流失估算？
输出：{{"experiment":"soil_erosion_rusle","intent":"sweep","params":{{}},"sweep_parameter":"vegetation_cover_pct","compare_variants":null,"reason":"问的是覆盖度与流失量的关系曲线","confidence":0.9}}

问题：同一块坡地，改成梯田或退耕还林之后，土壤流失量能减少多少？请做对照。
输出：{{"experiment":"soil_erosion_rusle","intent":"compare","params":{{}},"sweep_parameter":null,"compare_variants":[{{"label":"等高耕作","params":{{"practice":"contour_tillage"}}}},{{"label":"梯田","params":{{"practice":"terracing"}}}},{{"label":"退耕还林还草","params":{{"practice":"reforestation"}}}}],"reason":"比较不同保持措施的减沙效果","confidence":0.92}}

问题：对这块坡地的土壤流失来说，覆盖度和坡度哪个因子影响最大？
输出：{{"experiment":"soil_erosion_rusle","intent":"analyze","params":{{}},"sweep_parameter":null,"compare_variants":null,"reason":"问的是因子重要性排序","confidence":0.9}}

问题：河宽不变的情况下，弯道半径变小，凹岸的冲刷会变成什么样？
输出：{{"experiment":"river_bend_erosion","intent":"sweep","params":{{}},"sweep_parameter":"bend_radius_m","compare_variants":null,"reason":"扫弯道半径看冲刷强度的变化","confidence":0.88}}

问题：河宽 30 米、半径 60 米的急弯，凹岸剪应力和岸坡起动条件相比如何？
输出：{{"experiment":"river_bend_erosion","intent":"run","params":{{"bend_radius_m":60,"channel_width_m":30}},"sweep_parameter":null,"compare_variants":null,"reason":"给了明确几何参数，做单次计算","confidence":0.9}}
"""


def _catalog_text() -> str:
    """从注册表生成实验与参数清单，避免提示词和代码不同步。"""
    blocks: List[str] = []
    for exp in REGISTRY.values():
        lines = [f"## {exp.id}", f"名称：{exp.title}", f"说明：{exp.summary}", "参数："]
        for p in exp.parameters:
            if p.kind == "number":
                rng = f"{p.minimum:g} ~ {p.maximum:g} {p.unit}".strip()
            elif p.kind == "enum":
                rng = " / ".join(str(c["value"]) for c in (p.choices or []))
            else:
                rng = "true / false"
            opt = "，可留空" if p.optional else ""
            lines.append(f"  - {p.name}（{p.label}）：{rng}{opt}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _system_prompt() -> str:
    return SYSTEM_TMPL.format(catalog=_catalog_text(), mode_defs=MODE_DEFS)


def _repair(raw: Dict[str, Any], text: str) -> Dict[str, Any]:
    """把模型输出校正成与规则路由一致的结构。"""
    exp_id = raw.get("experiment")
    intent = raw.get("intent")

    if intent == "cross_module":
        return {"_cross": True, "reason": raw.get("reason") or "跨尺度关联探究"}

    if exp_id is None:
        return {"_refuse": True, "reason": raw.get("reason") or "无法映射到已有实验"}

    if exp_id not in REGISTRY:
        raise LLMError(f"模型给出了不存在的实验 {exp_id!r}")
    exp = REGISTRY[exp_id]

    if intent not in VALID_MODES:
        intent = "run"

    # 参数：只保留真实存在的名字，类型交给 coerce
    params = rule_router._default_params(exp)
    given = raw.get("params") or {}
    if isinstance(given, dict):
        for name, value in given.items():
            if exp.param(name) is None:
                continue
            params[name] = value

    plan: Dict[str, Any] = {"mode": intent}
    warnings: List[str] = []

    if intent == "sweep":
        sweep_param = raw.get("sweep_parameter")
        if sweep_param is None or exp.param(sweep_param) is None:
            sweep_param = rule_router._default_topic(exp_id)
            warnings.append(f"模型给的自变量不合法，已回退为 {sweep_param}")
        plan["parameter"] = sweep_param
        curated = (rule_router.TOPIC_SWEEP.get(sweep_param)
                   or rule_router.DEFAULT_SWEEP_VALUES.get(sweep_param))
        if curated:
            plan["values"] = curated

    if intent == "compare":
        variants = raw.get("compare_variants")
        if not isinstance(variants, list) or not variants:
            key = rule_router._default_topic(exp_id) if exp_id == "river_bend_erosion" else "practice"
            variants = (rule_router.COMPARE_PRESETS.get(key)
                        or rule_router._generic_variants(exp, key))
            warnings.append("模型没给出对照方案，已使用默认对照")
        clean = []
        for v in variants[:12]:
            if not isinstance(v, dict):
                continue
            vp = v.get("params") or {}
            vp = {k: val for k, val in vp.items() if exp.param(k) is not None}
            # 与基准组完全相同的方案会变成一行 0% 的废话，直接丢掉
            if vp and all(params.get(k) == val for k, val in vp.items()):
                continue
            clean.append({"label": str(v.get("label") or "对照")[:24], "params": vp})
        if not clean:
            clean = rule_router._generic_variants(exp, "practice")
        plan["variants"] = clean

    if intent == "analyze":
        plan["outputs"] = [getattr(exp, "primary_output", "") or exp.outputs[0]["key"]]

    # 参数预检：不改值，只报告，让工具那边去拒绝
    precheck: List[Dict[str, Any]] = []
    for name, value in (raw.get("params") or {}).items():
        p = exp.param(name)
        if p is None or p.kind != "number":
            continue
        try:
            fv = float(value)
        except (TypeError, ValueError):
            precheck.append({"field": name, "message": f"{p.label} 不是数值：{value!r}"})
            continue
        if p.minimum is not None and fv < p.minimum:
            precheck.append({"field": name, "message": f"{p.label}={fv:g} 低于允许下限 {p.minimum:g}"})
        if p.maximum is not None and fv > p.maximum:
            precheck.append({"field": name, "message": f"{p.label}={fv:g} 高于允许上限 {p.maximum:g}"})

    if precheck:
        warnings.append("参数越界已识别：工具会拒绝执行并返回允许范围。")

    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    return {
        "ok": True,
        "intent": intent,
        "experiment": exp_id,
        "experiment_title": exp.title,
        "confidence": round(confidence, 2),
        "params": params,
        "plan": plan,
        "reasoning": [raw.get("reason") or "模型判定"],
        "steps": [
            "理解问题并识别实验类型",
            "生成变量控制方案",
            "校验参数范围与单位",
            "调用实验工具计算",
            "核对结果并生成解释",
        ],
        "warnings": warnings,
        "precheck_errors": precheck,
    }


def route(text: str, config: Optional[LLMConfig] = None) -> Dict[str, Any]:
    """大模型路由。任何异常都会回退到规则路由，并在 engine 字段标明。"""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "输入为空",
                "clarify": "请描述你想探究的地理问题，例如「植被覆盖变化会怎样影响土壤流失？」"}

    cfg = config or load_config()
    if cfg is None:
        plan = rule_router.route(text)
        plan["engine"] = "rule（未配置模型服务）"
        return plan

    try:
        raw, meta = chat_json(
            [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": text},
            ],
            cfg,
            max_tokens=500,
        )
    except LLMError as exc:
        plan = rule_router.route(text)
        plan["engine"] = "rule（模型调用失败已回退）"
        plan["fallback_reason"] = str(exc)[:200]
        return plan

    try:
        repaired = _repair(raw, text)
    except LLMError as exc:
        plan = rule_router.route(text)
        plan["engine"] = "rule（模型输出不合法已回退）"
        plan["fallback_reason"] = str(exc)[:200]
        plan["llm"] = meta
        return plan

    if repaired.get("_cross"):
        return {
            "ok": True,
            "engine": "llm",
            "intent": "cross_module",
            "experiment": None,
            "confidence": 0.85,
            "experiments": list(REGISTRY.keys()),
            "plan": {"mode": "concept_link"},
            "params": {},
            "reasoning": [repaired.get("reason") or "跨尺度关联探究"],
            "steps": ["识别为跨模块探究", "分别生成两个实验的观察建议", "只做概念串联，不拼接数值"],
            "explanation": (
                "这个问题跨越两个尺度，正确的处理方式是**分别观察、概念串联**：\n"
                "① 坡面尺度（水土流失模型）：回答「有多少泥沙离开坡面」。\n"
                "② 河道尺度（弯道模型）：回答「进入河道后，泥沙在哪些部位倾向落淤」。\n"
                "两者之间是「供给—搬运—沉积」的因果链，但两个模型的数值口径不同，"
                "**不应把坡面的 t/(ha·a) 与河道的 Pa 剪应力直接拼成一个预测结果**。"
            ),
            "warnings": ["跨模块只做概念解释，不生成合并数值，避免不同尺度结果被误读为预测。"],
            "precheck_errors": [],
            "llm": meta,
        }

    if repaired.get("_refuse"):
        return {
            "ok": False,
            "engine": "llm",
            "error": "未识别出可执行的实验",
            "clarify": (
                "我目前能执行两类实验：\n"
                "① 坡面水土流失估算（覆盖度、坡度、坡长、梯田、退耕）\n"
                "② 弯道侵蚀与沉积倾向（弯道、凹岸、凸岸、冲刷、淤积）\n"
                "请把问题落到其中一个上，或点下面的示例任务。"
            ),
            "candidates": [t["text"] for t in rule_router.TASK_LIBRARY],
            "reasoning": [repaired.get("reason") or ""],
            "llm": meta,
        }

    repaired["engine"] = "llm"
    repaired["llm"] = meta
    return repaired


def route_with_engine(text: str, engine: str = "auto") -> Dict[str, Any]:
    """engine: rule | llm | auto（auto = 有 key 走模型，否则规则）"""
    if engine == "rule":
        plan = rule_router.route(text)
        plan["engine"] = "rule"
        return plan
    if engine == "llm":
        return route(text)
    # auto
    if load_config() is None:
        plan = rule_router.route(text)
        plan["engine"] = "rule（未配置模型服务）"
        return plan
    return route(text)

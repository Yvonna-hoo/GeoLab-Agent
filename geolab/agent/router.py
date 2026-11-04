# -*- coding: utf-8 -*-
"""规则式任务路由：自然语言 → 结构化实验方案。

为什么先用规则而不是直接上大模型？
1. 它能在**没有任何 API Key、没有网络**的情况下把端到端链路演示完整；
2. 它给出了一个可回归的基线（baseline），后面接大模型时可以逐条比对，
   证明「加了大模型是否真的更好」，而不是凭感觉说好；
3. 关键词、参数抽取和意图判据都是可读、可审计的，答辩时经得起追问。

大模型版本只需替换 route()，接口保持不变。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..registry import REGISTRY

# 每个实验的触发词（比 Experiment.keywords 更口语化，专门用于自然语言）
TRIGGERS: Dict[str, List[str]] = {
    "soil_erosion_rusle": [
        "水土流失", "土壤侵蚀", "流失量", "侵蚀量", "坡面", "坡度", "坡长",
        "植被覆盖", "覆盖度", "种草", "种树", "退耕", "梯田", "等高耕作",
        "RUSLE", "保土", "保持措施", "泥沙来源",
    ],
    "river_bend_erosion": [
        "河流", "河道", "弯道", "弯曲", "凹岸", "凸岸", "边滩", "河湾",
        "冲刷", "淤积", "沉积", "河床", "岸坡", "曲流",
    ],
}

CROSS_WORDS = ["联系", "关系", "为什么", "搬运", "但", "同时", "结合", "两者", "两个实验"]

# 意图判据用正则而不是关键词：中文问法太散，"会怎样变化""会变成什么样""怎么变"
# 是一回事，硬枚举关键词会漏。优先级：敏感性 > 对照 > 扫描 > 单次。
ANALYZE_PATTERNS = [
    r"最敏感", r"敏感性", r"哪个因子", r"影响最大", r"最关键",
    r"贡献最大", r"主要.{0,4}(?:哪个|什么)因子",
]

COMPARE_PATTERNS = [
    r"对照", r"比较", r"对比", r"哪个", r"哪种", r"更好",
    r"优劣", r"差异", r"区别", r"方案.{0,4}(?:选|比)",
]

SWEEP_PATTERNS = [
    r"怎样(?:变化|变|影响)", r"如何(?:变化|变|影响)", r"怎么(?:变|变化)",
    r"会(?:怎样|怎么|如何)", r"变化(?:趋势|规律)", r"趋势", r"线性", r"成比例",
    r"(?:增加|减少|降低|升高|增大|延长|缩短)多少",
    r"从\s*\d[^，。]{0,8}(?:到|变到|增至|增加到|延长到|延长至)",
    r"越[^，。]{0,12}越", r"随[^，。]{0,10}(?:变化|增大|增加|减少)",
    r"变成什么样", r"受影响",
]

# 各实验里「改这个参数可以回答哪类问题」的映射
PARAM_BY_TOPIC: Dict[str, List[Tuple[List[str], str, str]]] = {
    "soil_erosion_rusle": [
        # 顺序有讲究：「退耕还林」同时含「林」，若先匹配覆盖度就会认错话题
        (["措施", "梯田", "耕作", "退耕", "治理"], "practice", "水土保持措施"),
        (["覆盖", "植被", "种草", "种树", "林", "草"], "vegetation_cover_pct", "植被覆盖度"),
        (["坡度", "陡", "倾斜"], "slope_percent", "坡度"),
        (["坡长", "长坡"], "slope_length_m", "坡长"),
        (["降雨", "降水", "雨量"], "rainfall_erosivity", "降雨侵蚀力"),
        (["土壤", "土质", "可蚀性"], "soil_erodibility", "土壤可蚀性"),
    ],
    "river_bend_erosion": [
        (["半径", "曲率", "急弯"], "bend_radius_m", "弯道半径"),
        (["河宽", "宽度"], "channel_width_m", "河宽"),
        (["流速", "流量", "水速"], "mean_velocity_ms", "断面平均流速"),
        (["水深", "深浅"], "depth_m", "水深"),
        (["岸坡", "材质", "砂岸", "黏土", "岩石", "护岸"], "bank_material", "岸坡材质"),
        (["转角", "弯度"], "bend_angle_deg", "弯道转角"),
    ],
}

DEFAULT_SWEEP_VALUES: Dict[str, List[Any]] = {
    "vegetation_cover_pct": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    "slope_percent": [0, 2, 5, 8, 12, 16, 20, 25, 30, 40],
    "slope_length_m": [5, 10, 20, 30, 50, 80, 120, 200],
    "rainfall_erosivity": [1000, 2000, 3000, 4000, 5000, 6000, 8000],
    "bend_radius_m": [40, 60, 90, 120, 150, 200, 300, 500, 800],
    "mean_velocity_ms": [0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0, 2.5],
    "channel_width_m": [20, 30, 40, 60, 80, 100, 150, 200],
}

TASK_LIBRARY: List[Dict[str, str]] = [
    {
        "id": "A",
        "title": "任务A｜植被覆盖与土壤流失",
        "text": "在其他条件不变时，植被覆盖变化会怎样影响土壤流失估算？",
    },
    {
        "id": "B",
        "title": "任务B｜弯道冲刷部位",
        "text": "弯曲河道的哪些部位更容易发生侵蚀或沉积？",
    },
    {
        "id": "C",
        "title": "任务C｜治理措施对照",
        "text": "同一块坡地，改成梯田或退耕还林之后，土壤流失量能减少多少？请做对照。",
    },
    {
        "id": "D",
        "title": "任务D｜哪个因子最敏感",
        "text": "对这块坡地的土壤流失来说，覆盖度和坡度哪个因子影响最大？请做敏感性分析。",
    },
    {
        "id": "E",
        "title": "任务E｜急弯与缓弯对比",
        "text": "河宽不变的情况下，弯道半径变小，凹岸的冲刷会变成什么样？",
    },
    {
        "id": "F",
        "title": "任务F｜跨模块关联探究",
        "text": "坡面产生的泥沙与河流的搬运、沉积有什么联系？",
    },
    {
        "id": "G",
        "title": "任务G｜越界参数的自纠正",
        "text": "把植被覆盖度设成 130%，看看土壤流失量是多少。",
    },
]


def _hits(text: str, words: List[str]) -> List[str]:
    return [w for w in words if w in text]


def _matches(text: str, patterns: List[str]) -> List[str]:
    return [p for p in patterns if re.search(p, text)]


def _extract_numbers(text: str, patterns: Dict[str, str]) -> Dict[str, float]:
    found: Dict[str, float] = {}
    for name, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            try:
                found[name] = float(m.group(1))
            except (TypeError, ValueError):
                pass
    return found


NUM_PATTERNS: Dict[str, Dict[str, str]] = {
    "soil_erosion_rusle": {
        "slope_percent": r"坡度\s*(?:约|为|是)?\s*(\d+(?:\.\d+)?)\s*%",
        "slope_length_m": r"坡长\s*(?:约|为|是)?\s*(\d+(?:\.\d+)?)\s*(?:米|m)",
        "vegetation_cover_pct": r"(?:覆盖度|植被覆盖|覆盖率)\s*(?:约|为|是|设成|设为)?\s*(\d+(?:\.\d+)?)\s*%",
        "rainfall_erosivity": r"降雨侵蚀力\s*(?:约|为|是)?\s*(\d+(?:\.\d+)?)",
    },
    "river_bend_erosion": {
        "bend_radius_m": r"(?:半径|曲率半径)\s*(?:约|为|是)?\s*(\d+(?:\.\d+)?)\s*(?:米|m)?",
        "channel_width_m": r"河宽\s*(?:约|为|是)?\s*(\d+(?:\.\d+)?)\s*(?:米|m)?",
        "mean_velocity_ms": r"(?:流速)\s*(?:约|为|是)?\s*(\d+(?:\.\d+)?)\s*(?:m/s|米/秒)?",
        "depth_m": r"水深\s*(?:约|为|是)?\s*(\d+(?:\.\d+)?)\s*(?:米|m)?",
    },
}

# 话题 → 该话题下自然的参数扫描范围
TOPIC_SWEEP: Dict[str, List[Any]] = {
    "vegetation_cover_pct": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    "slope_percent": [0, 2, 5, 8, 12, 16, 20, 25, 30, 40],
    "slope_length_m": [5, 10, 20, 30, 50, 80, 120, 200],
    "bend_radius_m": [40, 60, 90, 120, 150, 200, 300, 500, 800],
    "mean_velocity_ms": [0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0, 2.5],
}

# 对比方案：常见「措施 → 参数组」
COMPARE_PRESETS: Dict[str, List[Dict[str, Any]]] = {
    "practice": [
        {"label": "等高耕作", "params": {"practice": "contour_tillage"}},
        {"label": "等高带状间作", "params": {"practice": "contour_strip"}},
        {"label": "梯田", "params": {"practice": "terracing"}},
        {"label": "退耕还林还草", "params": {"practice": "reforestation"}},
    ],
    "vegetation_cover_pct": [
        {"label": "裸地（0%）", "params": {"vegetation_cover_pct": 0}},
        {"label": "稀疏（30%）", "params": {"vegetation_cover_pct": 30}},
        {"label": "中等（60%）", "params": {"vegetation_cover_pct": 60}},
        {"label": "良好（85%）", "params": {"vegetation_cover_pct": 85}},
    ],
}


def _pick_experiment(text: str) -> Tuple[Optional[str], Dict[str, List[str]]]:
    scores: Dict[str, List[str]] = {}
    for exp_id, words in TRIGGERS.items():
        matched = _hits(text, words)
        if matched:
            scores[exp_id] = matched
    if not scores:
        return None, {}
    best = max(scores.items(), key=lambda kv: len(kv[1]))
    return best[0], scores


def _default_params(exp) -> Dict[str, Any]:
    return {p.name: p.default for p in exp.parameters}


def route(text: str) -> Dict[str, Any]:
    """把一句自然语言变成可执行的实验方案。"""
    text = (text or "").strip()
    if not text:
        return {
            "ok": False,
            "error": "输入为空",
            "clarify": "请描述你想探究的地理问题，例如「植被覆盖变化会怎样影响土壤流失？」",
        }

    exp_id, scores = _pick_experiment(text)

    # 跨模块：同时命中两个实验，并且出现了「联系 / 搬运」之类的关联词
    if len(scores) >= 2 and _hits(text, CROSS_WORDS):
        return {
            "ok": True,
            "intent": "cross_module",
            "experiment": None,
            "confidence": 0.7,
            "experiments": list(scores.keys()),
            "plan": {"mode": "concept_link"},
            "params": {},
            "reasoning": [
                f"同时命中两个实验的关键词：{ {k: v for k, v in scores.items()} }",
                "识别到关联探究意图（联系 / 搬运 / 沉积）",
            ],
            "steps": ["识别为跨模块探究", "分别生成两个实验的观察建议", "只做概念串联，不拼接数值"],
            "explanation": (
                "这个问题跨越两个尺度，正确的处理方式是**分别观察、概念串联**：\n"
                "① 坡面尺度（水土流失模型）：回答「有多少泥沙离开坡面」。\n"
                "② 河道尺度（弯道模型）：回答「进入河道后，泥沙在哪些部位倾向落淤」。\n"
                "两者之间是「供给—搬运—沉积」的因果链，但两个模型的数值口径不同，"
                "**不应把坡面的 t/(ha·a) 与河道的 Pa 剪应力直接拼成一个预测结果**。"
            ),
            "warnings": ["跨模块只做概念解释，不生成合并数值，避免不同尺度结果被误读为预测。"],
            "followups": ["先在水土流失实验中做覆盖度对照", "再到弯道实验中观察凸岸沉积带"],
        }

    if exp_id is None:
        return {
            "ok": False,
            "error": "未识别出可执行的实验",
            "clarify": (
                "我目前能执行两类实验：\n"
                "① 坡面水土流失估算（关键词：覆盖度、坡度、坡长、梯田、退耕）\n"
                "② 弯道侵蚀与沉积倾向（关键词：弯道、凹岸、凸岸、冲刷、淤积）\n"
                "请把问题落到其中一个上，或直接点下面的示例任务。"
            ),
            "candidates": [t["text"] for t in TASK_LIBRARY],
        }

    exp = REGISTRY[exp_id]
    params = _default_params(exp)

    # 抽取显式数值
    numbers = _extract_numbers(text, NUM_PATTERNS.get(exp_id, {}))
    params.update(numbers)

    # 判断模式
    mode = "run"
    if _matches(text, ANALYZE_PATTERNS):
        mode = "analyze"
    elif _matches(text, COMPARE_PATTERNS):
        mode = "compare"
    elif _matches(text, SWEEP_PATTERNS):
        mode = "sweep"

    # 话题 → 目标参数
    topic_param: Optional[str] = None
    topic_label = ""
    for words, pname, plabel in PARAM_BY_TOPIC.get(exp_id, []):
        if _hits(text, words):
            topic_param = pname
            topic_label = plabel
            break

    plan: Dict[str, Any] = {"mode": mode}
    reasoning: List[str] = [
        f"命中「{exp.title}」关键词：{'、'.join(scores[exp_id][:6])}",
    ]

    if mode == "sweep":
        sweep_param = topic_param or _default_topic(exp_id)
        plan["parameter"] = sweep_param
        # 只在有「贴合教学直觉」的取值序列时才给 values；
        # 否则留给服务层按参数自身量程自动生成（枚举会自动取全部选项）。
        curated = TOPIC_SWEEP.get(sweep_param) or DEFAULT_SWEEP_VALUES.get(sweep_param)
        if curated:
            plan["values"] = curated
        reasoning.append(f"判为「单参数扫描」：以「{topic_label or sweep_param}」为自变量")

    elif mode == "compare":
        comp_key = "practice" if (topic_param == "practice" or _hits(text, ["措施", "梯田", "退耕", "耕作"])) else None
        comp_key = comp_key or topic_param or "vegetation_cover_pct"
        preset = COMPARE_PRESETS.get(comp_key) or _generic_variants(exp, comp_key)
        plan["variants"] = preset
        comp_param = exp.param(comp_key)
        comp_label = comp_param.label if comp_param else comp_key
        reasoning.append(f"判为「对照组实验」：围绕「{comp_label}」设置 {len(preset)} 组对照")

    elif mode == "analyze":
        plan["outputs"] = [getattr(exp, "primary_output", "") or exp.outputs[0]["key"]]
        reasoning.append("判为「敏感性分析」：计算各因子弹性系数并排序")

    if numbers:
        reasoning.append(f"从问题中抽取到显式参数：{numbers}")

    # 参数合理性预检（让智能体在调用工具前就发现问题）
    warnings: List[str] = []
    errors: List[Dict[str, Any]] = []
    for name, value in numbers.items():
        p = exp.param(name)
        if p is None:
            continue
        if p.minimum is not None and value < p.minimum:
            errors.append({"field": name, "message": f"{p.label}={value:g} 低于允许下限 {p.minimum:g}"})
        if p.maximum is not None and value > p.maximum:
            errors.append({"field": name, "message": f"{p.label}={value:g} 高于允许上限 {p.maximum:g}"})

    if errors:
        warnings.append(
            "参数越界已被识别，工具会拒绝执行并返回允许范围。"
            "这正是「不让大模型自己编数值」的那道闸门。"
        )

    return {
        "ok": True,
        "intent": mode,
        "experiment": exp_id,
        "experiment_title": exp.title,
        "confidence": round(min(0.95, 0.45 + 0.1 * len(scores.get(exp_id, []))), 2),
        "params": params,
        "plan": plan,
        "reasoning": reasoning,
        "steps": [
            "理解问题并识别实验类型",
            "生成变量控制方案",
            "校验参数范围与单位",
            "调用实验工具计算",
            "核对结果并生成解释",
        ],
        "warnings": warnings,
        "precheck_errors": errors,
    }


def _default_topic(exp_id: str) -> str:
    return "vegetation_cover_pct" if exp_id == "soil_erosion_rusle" else "bend_radius_m"


def _generic_variants(exp, name: str) -> List[Dict[str, Any]]:
    """没有预置对照方案时，按参数类型临时生成一组有意义的对照。"""
    p = exp.param(name)
    if p is None:
        return []
    if p.kind == "enum":
        # 跳过与默认值相同的选项：那就是基准组本身，列进对照表会多出一行 0% 的废话
        return [
            {"label": c["label"], "params": {name: c["value"]}}
            for c in (p.choices or []) if c["value"] != p.default
        ]
    if p.minimum is None or p.maximum is None:
        return []
    lo, hi = float(p.minimum), float(p.maximum)
    out = []
    for frac in (0.25, 0.5, 0.75):
        value = round(lo + (hi - lo) * frac, 4)
        out.append({"label": f"{p.label} {value:g}{p.unit}", "params": {name: value}})
    return out


def build_payload(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把一个路由结果翻译成 /api/execute 的请求体。

    这样「路由」与「执行」之间只有一个明确的接缝，测试和评测脚本共用它，
    不必各自再拼一遍 payload。
    """
    if not plan or not plan.get("ok") or plan.get("intent") == "cross_module":
        return None
    payload: Dict[str, Any] = {
        "experiment": plan["experiment"],
        "mode": plan["intent"],
        "params": dict(plan.get("params") or {}),
    }
    spec = plan.get("plan") or {}
    if plan["intent"] == "sweep":
        sweep: Dict[str, Any] = {"parameter": spec.get("parameter")}
        if spec.get("values"):
            sweep["values"] = spec["values"]
        payload["sweep"] = sweep
    elif plan["intent"] == "compare":
        payload["compare"] = {"variants": spec.get("variants") or []}
    return payload


def tasks() -> List[Dict[str, str]]:
    return TASK_LIBRARY

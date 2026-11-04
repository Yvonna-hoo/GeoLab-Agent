# -*- coding: utf-8 -*-
"""实验一：坡面水土流失估算（RUSLE 因子框架）。

定位：**教学用的多年平均流失量示例估算**，不是实时侵蚀预报，也不是工程设计的
水土保持方案依据。所有因子取值、单位与适用范围都会随结果一起返回。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from ..protocol import Param, Experiment, numeric_elasticity  # noqa: F401

# 水利部《土壤侵蚀分类分级标准》SL 190-2007，水力侵蚀（t/(ha·a)）
EROSION_CLASSES: List[Tuple[float, str, str]] = [
    (2.0, "微度", "#3aa675"),
    (5.0, "轻度", "#8cc63f"),
    (10.0, "中度", "#f2c313"),
    (20.0, "强烈", "#ef8b26"),
    (40.0, "极强烈", "#dd4b39"),
    (float("inf"), "剧烈", "#8e2b23"),
]

# 水土保持措施因子 P 的典型取值（同一措施在文献中的范围很宽，这里取中值并明示可调）
PRACTICES: List[Dict[str, Any]] = [
    {"value": "none", "label": "无措施（顺坡耕作）", "p": 1.00},
    {"value": "contour_tillage", "label": "等高耕作", "p": 0.55},
    {"value": "contour_strip", "label": "等高带状间作", "p": 0.35},
    {"value": "terracing", "label": "梯田", "p": 0.20},
    {"value": "reforestation", "label": "退耕还林还草", "p": 0.05},
]


def classify_erosion(rate: float) -> Tuple[str, str]:
    """按 SL 190-2007 的水力侵蚀强度分级返回 (等级名, 颜色)。"""
    for threshold, name, color in EROSION_CLASSES:
        if rate < threshold:
            return name, color
    return "剧烈", "#8e2b23"


def slope_steepness(theta_rad: float) -> float:
    """坡度因子 S（McCool et al. 1987；陡坡段用 Nearing 1997 修正式）。"""
    sin_t = math.sin(theta_rad)
    tan_t = math.tan(theta_rad)
    if tan_t < 0.5:            # 约 26.6° 以下
        return 10.8 * sin_t + 0.03
    return 16.8 * sin_t - 0.50


def slope_length_exponent(theta_rad: float) -> float:
    """坡长指数 m = β/(1+β)（Renard et al. 1997）。"""
    sin_t = math.sin(theta_rad)
    beta = (sin_t / 0.0896) / (3.0 * sin_t ** 0.8 + 0.56)
    return beta / (1.0 + beta)


def ls_factor(slope_percent: float, slope_length_m: float) -> Dict[str, float]:
    """坡度坡长因子 LS = L × S。"""
    theta = math.atan(max(slope_percent, 0.0) / 100.0)
    m = slope_length_exponent(theta)
    length_ratio = max(slope_length_m, 1e-6) / 22.13
    l_factor = length_ratio ** m
    s_factor = slope_steepness(theta)
    return {
        "L": l_factor,
        "S": s_factor,
        "LS": l_factor * s_factor,
        "m": m,
        "theta_deg": math.degrees(theta),
    }


def cover_to_c(cover_percent: float, decay: float) -> float:
    """由植被覆盖度估算覆盖管理因子 C。

    使用指数衰减形式 C = exp(-decay × 覆盖度%)，满足 C(0%)=1、C(100%)→小值。
    **这是教学用简化映射，不是权威 C 因子表**；decay 可调，也可直接给定 C。
    """
    return math.exp(-decay * max(cover_percent, 0.0))


def practice_factor(key: str) -> float:
    for item in PRACTICES:
        if item["value"] == key:
            return float(item["p"])
    return 1.0


class SoilErosionRUSLE(Experiment):
    id = "soil_erosion_rusle"
    title = "坡面水土流失（RUSLE 因子估算）"
    summary = (
        "按 RUSLE 的 A = R·K·LS·C·P 结构估算多年平均土壤流失量，"
        "支持单因子对照与敏感性分析，用于理解植被、坡度与治理措施的作用方向与量级。"
    )
    version = "1.1.0"
    domain = "水土保持 / 地貌过程"

    parameters = [
        Param(
            name="rainfall_erosivity", label="降雨侵蚀力 R", unit="MJ·mm/(ha·h·a)",
            minimum=100, maximum=20000, default=4500, step=100,
            description="降雨动能与强度的综合指标。数量级参考：半湿润区 1000~2500，湿润区 4000~8000。应以当地气象站计算值替换。",
            source="Wischmeier & Smith 1978；Renard et al. 1997",
        ),
        Param(
            name="soil_erodibility", label="土壤可蚀性 K", unit="t·h/(MJ·mm)",
            minimum=0.005, maximum=0.08, default=0.030, step=0.001,
            description="土壤对雨滴击溅与径流剥离的敏感程度。砂土约 0.02~0.03，壤土约 0.04~0.05，黏土约 0.02。",
            source="Renard et al. 1997（可蚀性诺谟图）",
        ),
        Param(
            name="slope_percent", label="坡度", unit="%",
            minimum=0, maximum=60, default=8, step=0.5,
            description="地表坡度（百分比）。8% 约等于 4.6°，20% 约等于 11.3°。",
        ),
        Param(
            name="slope_length_m", label="坡长", unit="m",
            minimum=1, maximum=500, default=30, step=1,
            description="自上坡分水线起沿坡面方向的水平投影长度。",
        ),
        Param(
            name="vegetation_cover_pct", label="植被覆盖度", unit="%",
            minimum=0, maximum=100, default=60, step=1,
            description="地表被植被冠层与枯落物覆盖的比例。仅在未直接给定 C 因子时生效。",
        ),
        Param(
            name="cover_decay", label="覆盖衰减系数", unit="1/%",
            minimum=0.01, maximum=0.15, default=0.04, step=0.001,
            description="C = exp(-系数 × 覆盖度%) 中的系数。这是本模型最需要校准的假设，改动它比改动任何其他参数都更影响结论。",
        ),
        Param(
            name="cover_factor", label="覆盖管理因子 C（直接给定）", unit="",
            minimum=0.001, maximum=1.0, default=None, optional=True, step=0.001,
            description="若你有当地实测或文献 C 因子，可在此直接输入，将覆盖植被覆盖度的换算。留空则由覆盖度估算。",
        ),
        Param(
            name="practice", label="水土保持措施", kind="enum", default="none",
            choices=[{"value": p["value"], "label": f"{p['label']}（P={p['p']}）"} for p in PRACTICES],
            description="措施因子 P 取典型中值，实际范围因地形与实施质量而异。",
        ),
    ]

    assumptions = [
        "按 RUSLE 结构 A = R·K·LS·C·P 估算多年平均年流失量，假设坡面处于长期平均状态。",
        "坡度采用均一坡面，不做坡面分段（复杂地形需分段计算后汇总）。",
        "降雨侵蚀力 R 与土壤可蚀性 K 由使用者给定，本工具不做区域参数库匹配。",
        "C 因子若由覆盖度换算，采用指数衰减经验映射，属于教学简化。",
        "P 因子取文献典型中值，未考虑措施实施年限与维护状况。",
    ]
    limitations = [
        "结果为示例估算，不等同于实测输沙量，也不能用于水土保持工程设计与环评。",
        "RUSLE 不模拟细沟—切沟发育、坡面汇流路径与泥沙输移沉积过程。",
        "单次极端暴雨的侵蚀量会显著偏离多年平均值，本模型不适用于场次暴雨事件。",
        "区域内 R、K 的实际空间差异可能导致结果偏差数倍，务必替换为本地参数。",
    ]
    outputs = [
        {"key": "soil_loss_t_ha_yr", "label": "预测土壤流失量 A", "unit": "t/(ha·a)"},
        {"key": "soil_loss_t_km2_yr", "label": "换算为面积负荷", "unit": "t/(km²·a)"},
        {"key": "intensity_class", "label": "侵蚀强度等级", "unit": ""},
    ]
    keywords = ["水土流失", "土壤侵蚀", "RUSLE", "植被覆盖", "坡度", "梯田", "退耕还林", "保持措施"]
    primary_output = "soil_loss_t_ha_yr"

    # ------------------------------------------------------------------

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        r = float(params["rainfall_erosivity"])
        k = float(params["soil_erodibility"])
        slope = float(params["slope_percent"])
        length = float(params["slope_length_m"])
        cover = float(params["vegetation_cover_pct"])
        decay = float(params["cover_decay"])
        p_key = params["practice"]
        p_val = practice_factor(p_key)

        ls = ls_factor(slope, length)

        explicit_c = params.get("cover_factor")
        if explicit_c is not None:
            c_val = float(explicit_c)
            c_source = "用户直接给定"
        else:
            c_val = cover_to_c(cover, decay)
            c_source = f"由覆盖度 {cover:g}% 与衰减系数 {decay:g} 换算"

        a = r * k * ls["LS"] * c_val * p_val
        level, color = classify_erosion(a)
        practice_label = next(
            (item["label"] for item in PRACTICES if item["value"] == p_key), p_key
        )

        # 各因子对结果的相对贡献（用于讲清「哪一项在放大流失」）
        contributions = {
            "R": r, "K": k, "LS": ls["LS"], "C": c_val, "P": p_val,
        }

        headline = (
            f"坡度 {slope:g}%、坡长 {length:g} m、植被覆盖 {cover:g}%、"
            f"{practice_label}条件下，估算年流失量约 {a:.1f} t/(ha·a)，"
            f"属{level}侵蚀。"
        )

        return {
            "soil_loss_t_ha_yr": round(a, 3),
            "soil_loss_t_km2_yr": round(a * 100.0, 2),
            "intensity_class": level,
            "intensity_color": color,
            "factors": {key: round(val, 6) for key, val in contributions.items()},
            "ls_components": {
                "L": round(ls["L"], 4),
                "S": round(ls["S"], 4),
                "LS": round(ls["LS"], 4),
                "m": round(ls["m"], 4),
                "theta_deg": round(ls["theta_deg"], 3),
            },
            "cover_factor_source": c_source,
            "practice_label": practice_label,
            "headline": headline,
        }

    def check(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        notes: List[Dict[str, Any]] = []
        if params.get("cover_factor") is not None and params.get("vegetation_cover_pct"):
            pass  # 两个都给时以直接给定的 C 为准，前端已提示，不算错误
        return notes

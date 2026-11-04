# -*- coding: utf-8 -*-
"""实验二：弯曲河道侵蚀与沉积倾向（规则化教学模型）。

定位：**概念与规律演示模型**。它把一个成熟的定性认识——弯道中主流偏向凹岸、
横向环流把泥沙从凹岸搬向凸岸——写成可参数化、可重复计算的规则，
用于对比"弯道半径、河宽、流速、岸坡材质"改变时冲淤格局怎么变。

本模型**不**求解平面二维水沙方程，**不**声称能预测真实河床演变。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from ..protocol import Param, Experiment

# 岸坡材质：起动剪应力 τc（Pa，量级参考）与易蚀倍率
BANK_MATERIALS: List[Dict[str, Any]] = [
    {"value": "loose_sand", "label": "松散砂质岸", "tau_c": 2.0, "note": "极易冲刷，弯道外侧常快速后退"},
    {"value": "silt_loam", "label": "粉砂/壤土岸", "tau_c": 8.0, "note": "中等抗冲，常见于冲积平原河段"},
    {"value": "cohesive_clay", "label": "黏性土岸", "tau_c": 20.0, "note": "抗冲较强，但遇干湿交替易崩岸"},
    {"value": "rock_revetment", "label": "基岩或硬护岸", "tau_c": 80.0, "note": "基本不冲刷，冲淤格局受河床控制"},
]

TENDENCY_STYLES = {
    "强侵蚀": "#cf3b2e",
    "侵蚀": "#ef8b26",
    "冲淤平衡": "#b0b7c0",
    "沉积": "#4b93d1",
    "强沉积": "#1f5f9e",
}

RHO = 1000.0   # 水密度 kg/m³


def tendency_of(v_rel: float) -> str:
    """由相对流速给出冲淤倾向分类。

    判据是可解释的：弯道中横向流速偏离断面平均值的方向，决定该处是"流速偏大
    带走近岸泥沙"还是"流速偏小使泥沙落淤"。用 ±5% 作为平衡带。
    """
    index = 2.0 * (v_rel - 1.0)
    if index <= -0.35:
        return "强沉积"
    if index <= -0.10:
        return "沉积"
    if index <= 0.10:
        return "冲淤平衡"
    if index <= 0.35:
        return "侵蚀"
    return "强侵蚀"


def circulation_amplitude(rc_over_b: float) -> float:
    """横向流速偏离幅度 A0。

    弯道越急（Rc/B 越小），离心作用与横向环流越强，主流越偏向凹岸。
    A0 随 Rc/B 单调下降，并用上下界保证外推到极端几何时数值仍稳定。
    """
    raw = 0.15 + 0.5 / max(rc_over_b, 1e-6)
    return max(0.05, min(0.50, raw))


def along_bend_amplitude(t: float) -> float:
    """沿程幅度包络：进口为 0，出口为 0，峰值落在弯顶偏下游（t≈0.61）。

    这与"最大冲刷坑通常位于弯顶下游"的观测认识一致，是本模型刻意保留的形态特征。
    """
    tt = max(0.0, min(1.0, t))
    return math.sin(math.pi * (tt ** 1.4))


def angle_development(angle_deg: float) -> float:
    """弯道转角对环流发展的限制。

    转角很小（例如 15°）时，水流还来不及形成完整的横向环流，冲刷自然弱；
    转角增大后逐渐饱和。用 1−exp(−θ/60) 表达这一饱和过程：
    15° → 0.22，90° → 0.78，180° → 0.95，270° → 0.99。
    """
    return 1.0 - math.exp(-max(angle_deg, 0.0) / 60.0)


class RiverBendErosion(Experiment):
    id = "river_bend_erosion"
    title = "弯曲河道侵蚀与沉积倾向"
    summary = (
        "用规则化弯道模型计算断面内横向流速、床面剪应力与冲淤倾向分布，"
        "说明「凹岸冲刷、凸岸淤积」的机理及其随弯道曲率、流速与岸坡材质的变化。"
    )
    version = "1.1.0"
    domain = "河流地貌 / 流水作用"

    parameters = [
        Param(
            name="bend_radius_m", label="弯道中心线半径 Rc", unit="m",
            minimum=20, maximum=2000, default=150, step=5,
            description="河道中心线的曲率半径。半径越小表示弯道越急。",
        ),
        Param(
            name="channel_width_m", label="河宽 B", unit="m",
            minimum=5, maximum=500, default=60, step=1,
            description="弯道处水面宽度。Rc/B 是控制环流强弱的关键无量纲量。",
        ),
        Param(
            name="mean_velocity_ms", label="断面平均流速", unit="m/s",
            minimum=0.2, maximum=5.0, default=1.2, step=0.05,
            description="弯道段断面平均流速，用于估算床面剪应力量级。",
        ),
        Param(
            name="depth_m", label="平均水深", unit="m",
            minimum=0.5, maximum=15.0, default=3.0, step=0.1,
            description="弯道段平均水深，用于估算水流强度与相对水深（水深/河宽）。",
        ),
        Param(
            name="bend_angle_deg", label="弯道转角", unit="°",
            minimum=15, maximum=270, default=90, step=5,
            description="弯道从进口到出口中心线转折的总角度，决定环流发展沿程长度。",
        ),
        Param(
            name="roughness_f", label="达西阻力系数 f", unit="",
            minimum=0.02, maximum=0.08, default=0.03, step=0.005,
            description="用于 τ = ρ·(f/8)·v² 估算床面剪应力。沙质河床常见 0.02~0.04。",
        ),
        Param(
            name="bank_material", label="岸坡材质", kind="enum", default="silt_loam",
            choices=[{"value": m["value"], "label": f"{m['label']}（τc≈{m['tau_c']:g} Pa）"}
                     for m in BANK_MATERIALS],
            description="决定起动剪应力，用于判断「剪应力是否足以真正冲走泥沙」。",
        ),
    ]

    assumptions = [
        "河道为单一段等宽弯道，进口顺直、出口顺直，不考虑上下游弯道的叠加影响。",
        "断面平均流速沿程不变；横向流速按「偏离幅度 × 横向位置」的线性剖面近似，断面平均后仍等于平均流速。",
        "床面剪应力用 τ = ρ·(f/8)·v² 估算，属一维量级估算，未解二维流场。",
        "横向环流强度由 Rc/B 的经验关系给出，并乘以沿程发展系数 1−exp(−转角/60)：短弯段环流尚未充分发展，冲刷相应减弱。",
        "沿岸坡材质以单一 τc 表征抗冲性，不考虑土体含水率、植被根系与崩岸机制。",
    ]
    limitations = [
        "本模型是概念演示，不是二维水沙数值模型，不能预测真实河床冲淤量与演变过程。",
        "未计算泥沙输移率与河床变形，冲淤倾向只是「流速偏离方向」的定性推断。",
        "不适用于分汊河段、游荡型河段、河口潮汐河段与水库回水段。",
        "实际弯道冲刷坑深度还受来沙条件、床沙级配与护岸工程控制，本模型未涉及。",
    ]
    outputs = [
        {"key": "stress_exceed_ratio", "label": "剪应力超过起动条件倍数", "unit": "×"},
        {"key": "tau_max_pa", "label": "最大床面剪应力", "unit": "Pa"},
        {"key": "rc_over_b", "label": "弯道半径比 Rc/B", "unit": ""},
        {"key": "erosion_zone", "label": "主要侵蚀部位", "unit": ""},
        {"key": "deposition_zone", "label": "主要沉积部位", "unit": ""},
    ]
    keywords = ["河流", "弯道", "凹岸", "凸岸", "侵蚀", "沉积", "边滩", "河道演变"]
    # 用「剪应力超过起动条件倍数」作主指标：它同时含动力条件与岸坡抗性，
    # 换岸坡材质时才有可比的差异；只看 τ(Pa) 时换材质结果不变，容易误导。
    primary_output = "stress_exceed_ratio"

    N_PHI = 21   # 沿程采样数
    N_S = 9      # 横向采样数

    # ------------------------------------------------------------------

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        rc = float(params["bend_radius_m"])
        b = float(params["channel_width_m"])
        v_mean = float(params["mean_velocity_ms"])
        depth = float(params["depth_m"])
        angle = float(params["bend_angle_deg"])
        f = float(params["roughness_f"])
        material_key = params["bank_material"]

        material = next(
            (m for m in BANK_MATERIALS if m["value"] == material_key), BANK_MATERIALS[1]
        )
        tau_c = float(material["tau_c"])

        rc_over_b = rc / b
        # 环流强度 = 曲率效应（Rc/B）× 沿程发展程度（转角）
        base_amplitude = circulation_amplitude(rc_over_b)
        a0 = base_amplitude * angle_development(angle)

        shear_coeff = RHO * (f / 8.0)

        field: List[Dict[str, Any]] = []
        outer_profile: List[Dict[str, Any]] = []
        tau_values: List[float] = []

        for i in range(self.N_PHI):
            t = i / (self.N_PHI - 1)
            phi_deg = t * angle
            amp = a0 * along_bend_amplitude(t)
            row: List[Dict[str, Any]] = []
            for j in range(self.N_S):
                s = j / (self.N_S - 1)          # 0 = 凸岸(内侧), 1 = 凹岸(外侧)
                v_rel = 1.0 + amp * (2.0 * s - 1.0)
                v_rel = max(0.15, min(1.85, v_rel))
                v_abs = v_mean * v_rel
                tau = shear_coeff * v_abs * v_abs
                tau_values.append(tau)
                row.append({
                    "v_rel": round(v_rel, 4),
                    "tau_pa": round(tau, 3),
                    "tendency": tendency_of(v_rel),
                })
            field.append({"phi_pct": round(t * 100.0, 2), "cells": row})
            outer = row[-1]
            outer_profile.append({
                "phi_pct": round(t * 100.0, 2),
                "v_rel": outer["v_rel"],
                "tau_pa": outer["tau_pa"],
            })

        # 统计
        tau_max = max(tau_values)
        tau_min = min(tau_values)
        tau_mean = sum(tau_values) / len(tau_values)

        max_cell = self._extreme(field, want="max")
        min_cell = self._extreme(field, want="min")

        erosion_zone = (
            f"凹岸（外侧）沿程约 {max_cell['phi_pct']:.0f}% 处（弯顶偏下游）"
            if max_cell else "—"
        )

        # 沉积带通常是一条很长的内侧带，报告它的沿程范围比报一个点更有信息量
        dep_rows = [
            row["phi_pct"] for row in field
            if row["cells"][0]["tendency"] in ("沉积", "强沉积")
        ]
        if dep_rows:
            deposition_zone = f"沿程约 {min(dep_rows):.0f}%–{max(dep_rows):.0f}% 的带状沉积区"
        elif min_cell:
            deposition_zone = f"沿程约 {min_cell['phi_pct']:.0f}% 处（沉积偏弱）"
        else:
            deposition_zone = "—"

        # 剪应力是否真的超过起动条件
        exceed = tau_max / tau_c if tau_c > 0 else 0.0
        if exceed >= 1.0:
            material_verdict = (
                f"最大剪应力 {tau_max:.2f} Pa 已超过该材质的起动剪应力 {tau_c:.1f} Pa"
                f"（约 {exceed:.2f} 倍），凹岸存在实际冲刷风险。"
            )
        else:
            material_verdict = (
                f"最大剪应力 {tau_max:.2f} Pa 仍低于该材质的起动剪应力 {tau_c:.1f} Pa"
                f"（约 {exceed:.2f} 倍），流速虽偏向凹岸，但未必形成明显冲刷。"
            )

        headline = (
            f"Rc/B = {rc_over_b:.2f}，横向环流幅度 A0 = {a0:.2f}。"
            f"主流偏向凹岸，最大床面剪应力 {tau_max:.2f} Pa 出现在{erosion_zone}；"
            f"凸岸内侧流速最低，形成{deposition_zone}。"
        )

        return {
            "rc_over_b": round(rc_over_b, 3),
            "circulation_amplitude": round(a0, 4),
            "curvature_amplitude": round(base_amplitude, 4),
            "angle_development": round(angle_development(angle), 4),
            "tau_max_pa": round(tau_max, 3),
            "tau_min_pa": round(tau_min, 3),
            "tau_mean_pa": round(tau_mean, 3),
            "bank_tau_c_pa": tau_c,
            "stress_exceed_ratio": round(exceed, 3),
            "bank_material_label": material["label"],
            "bank_material_note": material["note"],
            "material_verdict": material_verdict,
            "erosion_zone": erosion_zone,
            "deposition_zone": deposition_zone,
            "max_cell": max_cell,
            "min_cell": min_cell,
            "field": field,
            "outer_bank_profile": outer_profile,
            "geometry": {
                "r_center_m": round(rc, 2),
                "r_inner_m": round(max(rc - b / 2.0, 1.0), 2),
                "r_outer_m": round(rc + b / 2.0, 2),
                "bend_angle_deg": round(angle, 2),
                "width_m": round(b, 2),
                "depth_m": round(depth, 2),
                "depth_over_width": round(depth / b, 4),
            },
            "tendency_legend": TENDENCY_STYLES,
            "headline": headline,
        }

    def _extreme(self, field: List[Dict[str, Any]], want: str):
        best = None
        best_val = None
        for row in field:
            for j, cell in enumerate(row["cells"]):
                if j == 0 or j == len(row["cells"]) - 1:  # 只看两岸
                    val = cell["v_rel"]
                    if best_val is None or (want == "max" and val > best_val) or (want == "min" and val < best_val):
                        best_val = val
                        best = {
                            "phi_pct": row["phi_pct"],
                            "side": "凹岸" if j else "凸岸",
                            "v_rel": cell["v_rel"],
                            "tau_pa": cell["tau_pa"],
                            "tendency": cell["tendency"],
                        }
        return best

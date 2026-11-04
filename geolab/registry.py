# -*- coding: utf-8 -*-
"""实验注册表。

新增一个实验只需要：写一个 Experiment 子类 → 在这里登记一行。
服务器、前端表单、任务路由、测试都会自动发现它——这是「可插拔 Skills」的落地方式。
"""
from __future__ import annotations

from typing import Dict, List

from .experiments.river_bend import RiverBendErosion
from .experiments.soil_erosion import SoilErosionRUSLE

REGISTRY: Dict[str, object] = {}


def register(experiment) -> None:
    REGISTRY[experiment.id] = experiment


register(SoilErosionRUSLE())
register(RiverBendErosion())


def catalog() -> List[dict]:
    """给前端与智能体用的实验清单。"""
    items = []
    for exp in REGISTRY.values():
        info = exp.describe()
        items.append(info)
    return items


def get(experiment_id: str):
    return REGISTRY.get(experiment_id)

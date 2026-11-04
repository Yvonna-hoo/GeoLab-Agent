# -*- coding: utf-8 -*-
"""实验内核集合。

新增实验：在此文件写下 Experiment 子类，然后在 geolab/registry.py 登记一行。
"""
from .river_bend import RiverBendErosion
from .soil_erosion import SoilErosionRUSLE

__all__ = ["SoilErosionRUSLE", "RiverBendErosion"]

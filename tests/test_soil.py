# -*- coding: utf-8 -*-
"""水土流失实验的物理一致性与回归测试。

这里刻意不只测「函数能跑」，而是测「关系方向对不对」：
覆盖度上升流失量必须下降、坡度上升必须上升、措施越强 P 必须越小。
任何一个方向反了，教学结论就错了。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geolab.experiments.soil_erosion import (  # noqa: E402
    SoilErosionRUSLE,
    classify_erosion,
    cover_to_c,
    ls_factor,
    practice_factor,
)


class TestLSFactor(unittest.TestCase):
    def test_reference_values(self):
        """独立手算的参考值：坡长取标准小区 22.13 m 时 L=1。"""
        r1 = ls_factor(9.0, 22.13)
        self.assertAlmostEqual(r1["L"], 1.0, places=6)
        self.assertAlmostEqual(r1["LS"], 0.9981, places=3)

        r2 = ls_factor(12.0, 50.0)
        self.assertAlmostEqual(r2["LS"], 2.054, places=2)

    def test_flat_slope_is_near_zero(self):
        r = ls_factor(0.0, 50.0)
        self.assertAlmostEqual(r["S"], 0.03, places=6)
        self.assertAlmostEqual(r["L"], 1.0, places=6)

    def test_monotonic(self):
        prev = -1.0
        for slope in (2, 5, 10, 15, 25, 40):
            cur = ls_factor(slope, 40.0)["LS"]
            self.assertGreater(cur, prev)
            prev = cur

    def test_steep_branch(self):
        """tanθ ≥ 0.5（约 26.6°）以后走 Nearing 修正式，S 仍应单调。"""
        a = ls_factor(28.0, 40.0)["S"]
        b = ls_factor(40.0, 40.0)["S"]
        self.assertGreater(b, a)


class TestCoverMapping(unittest.TestCase):
    def test_endpoints(self):
        self.assertAlmostEqual(cover_to_c(0, 0.04), 1.0, places=9)
        self.assertLess(cover_to_c(100, 0.04), 0.02)

    def test_monotonic_decrease(self):
        prev = 2.0
        for cover in range(0, 101, 10):
            cur = cover_to_c(cover, 0.04)
            self.assertLess(cur, prev)
            prev = cur


class TestPractice(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(practice_factor("none"), 1.0)
        self.assertLess(practice_factor("contour_tillage"), practice_factor("none"))
        self.assertLess(practice_factor("terracing"), practice_factor("contour_tillage"))
        self.assertLess(practice_factor("reforestation"), practice_factor("terracing"))


class TestClassification(unittest.TestCase):
    def test_sl190_boundaries(self):
        self.assertEqual(classify_erosion(1.9)[0], "微度")
        self.assertEqual(classify_erosion(2.0)[0], "轻度")
        self.assertEqual(classify_erosion(9.9)[0], "中度")
        self.assertEqual(classify_erosion(10.0)[0], "强烈")
        self.assertEqual(classify_erosion(39.9)[0], "极强烈")
        self.assertEqual(classify_erosion(40.0)[0], "剧烈")


class TestModelBehaviour(unittest.TestCase):
    def setUp(self):
        self.exp = SoilErosionRUSLE()
        self.base, _ = self.exp.validate({})

    def run_with(self, **over):
        p = dict(self.base)
        p.update(over)
        params, errs = self.exp.validate(p)
        self.assertEqual(errs, [])
        return self.exp.run(params)

    def test_identity(self):
        """A 必须严格等于 R·K·LS·C·P，不能有隐藏的额外修正。"""
        out = self.run_with()
        f = out["factors"]
        expect = f["R"] * f["K"] * f["LS"] * f["C"] * f["P"]
        self.assertAlmostEqual(out["soil_loss_t_ha_yr"], expect, places=2)

    def test_cover_reduces_loss(self):
        a = self.run_with(vegetation_cover_pct=0)["soil_loss_t_ha_yr"]
        b = self.run_with(vegetation_cover_pct=50)["soil_loss_t_ha_yr"]
        c = self.run_with(vegetation_cover_pct=95)["soil_loss_t_ha_yr"]
        self.assertGreater(a, b)
        self.assertGreater(b, c)

    def test_slope_increases_loss(self):
        a = self.run_with(slope_percent=3)["soil_loss_t_ha_yr"]
        b = self.run_with(slope_percent=15)["soil_loss_t_ha_yr"]
        self.assertGreater(b, a)

    def test_rain_and_erodibility_are_linear(self):
        o1 = self.run_with(rainfall_erosivity=2000)
        o2 = self.run_with(rainfall_erosivity=4000)
        self.assertAlmostEqual(o2["soil_loss_t_ha_yr"], o1["soil_loss_t_ha_yr"] * 2, places=2)

    def test_practice_reduces_loss(self):
        a = self.run_with(practice="none")["soil_loss_t_ha_yr"]
        b = self.run_with(practice="terracing")["soil_loss_t_ha_yr"]
        # 输出保留三位小数，比较时给 1e-3 的容差
        self.assertAlmostEqual(b / a, 0.20, delta=1e-3)

    def test_explicit_c_overrides_cover(self):
        out = self.run_with(cover_factor=0.5, vegetation_cover_pct=95)
        self.assertAlmostEqual(out["factors"]["C"], 0.5, places=6)
        self.assertIn("直接给定", out["cover_factor_source"])

    def test_headline_mentions_grade(self):
        out = self.run_with()
        self.assertIn(out["intensity_class"], out["headline"])


if __name__ == "__main__":
    unittest.main()

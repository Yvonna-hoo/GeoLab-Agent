# -*- coding: utf-8 -*-
"""弯道模型的机理测试。

重点验证四条「教科书结论」在模型里确实成立：
① 凹岸流速大于凸岸；② 弯道越急环流越强；③ 剪应力与流速平方成正比；
④ 岸坡越抗冲，同样的水流下冲刷越弱。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geolab.experiments.river_bend import (  # noqa: E402
    BANK_MATERIALS,
    RiverBendErosion,
    angle_development,
    circulation_amplitude,
    tendency_of,
)


class TestTendency(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(tendency_of(1.30), "强侵蚀")
        self.assertEqual(tendency_of(1.10), "侵蚀")
        self.assertEqual(tendency_of(1.00), "冲淤平衡")
        self.assertEqual(tendency_of(0.90), "沉积")
        self.assertEqual(tendency_of(0.70), "强沉积")

    def test_symmetric_around_one(self):
        self.assertEqual(tendency_of(1.0), "冲淤平衡")


class TestCirculation(unittest.TestCase):
    def test_tighter_bend_stronger(self):
        self.assertGreater(circulation_amplitude(1.0), circulation_amplitude(2.0))
        self.assertGreater(circulation_amplitude(2.0), circulation_amplitude(6.0))

    def test_bounded(self):
        self.assertLessEqual(circulation_amplitude(0.01), 0.50)
        self.assertGreaterEqual(circulation_amplitude(1000.0), 0.05)


class TestAngleDevelopment(unittest.TestCase):
    """转角必须真的起作用：15° 的微弯和 180° 的发卡弯不该给出同样的冲刷。"""

    def test_saturating(self):
        self.assertAlmostEqual(angle_development(0), 0.0, places=6)
        self.assertLess(angle_development(30), angle_development(90))
        self.assertLess(angle_development(90), angle_development(180))
        self.assertGreater(angle_development(10000), 0.99)

    def test_short_bend_weaker_than_long(self):
        exp = RiverBendErosion()
        base, _ = exp.validate({})
        short, _ = exp.validate(dict(base, bend_angle_deg=30))
        long_, _ = exp.validate(dict(base, bend_angle_deg=180))
        self.assertGreater(exp.run(long_)["stress_exceed_ratio"],
                           exp.run(short)["stress_exceed_ratio"])


class TestField(unittest.TestCase):
    def setUp(self):
        self.exp = RiverBendErosion()
        self.base, _ = self.exp.validate({})

    def run_with(self, **over):
        p = dict(self.base)
        p.update(over)
        params, errs = self.exp.validate(p)
        self.assertEqual(errs, [])
        return self.exp.run(params)

    def test_grid_shape(self):
        out = self.run_with()
        self.assertEqual(len(out["field"]), RiverBendErosion.N_PHI)
        self.assertEqual(len(out["field"][0]["cells"]), RiverBendErosion.N_S)

    def test_outer_bank_faster_than_inner(self):
        out = self.run_with()
        mid = out["field"][len(out["field"]) // 2]["cells"]
        self.assertGreater(mid[-1]["v_rel"], 1.0)   # 凹岸
        self.assertLess(mid[0]["v_rel"], 1.0)       # 凸岸
        self.assertGreater(mid[-1]["tau_pa"], mid[0]["tau_pa"])

    def test_cross_section_mean_is_preserved(self):
        """横向剖面围绕 1 对称，断面平均流速才自洽。"""
        out = self.run_with()
        mid = out["field"][len(out["field"]) // 2]["cells"]
        mean = sum(c["v_rel"] for c in mid) / len(mid)
        self.assertAlmostEqual(mean, 1.0, places=6)

    def test_peak_is_downstream_of_apex(self):
        out = self.run_with(bend_angle_deg=90)
        phi = out["max_cell"]["phi_pct"]
        self.assertGreater(phi, 50.0)
        self.assertLess(phi, 80.0)

    def test_tighter_bend_raises_shear(self):
        a = self.run_with(bend_radius_m=300)["tau_max_pa"]
        b = self.run_with(bend_radius_m=80)["tau_max_pa"]
        self.assertGreater(b, a)

    def test_shear_scales_with_velocity_squared(self):
        a = self.run_with(mean_velocity_ms=1.0)["tau_max_pa"]
        b = self.run_with(mean_velocity_ms=2.0)["tau_max_pa"]
        self.assertAlmostEqual(b / a, 4.0, delta=1e-3)

    def test_material_changes_verdict(self):
        sand = self.run_with(bank_material="loose_sand")
        rock = self.run_with(bank_material="rock_revetment")
        self.assertEqual(sand["tau_max_pa"], rock["tau_max_pa"])  # 水流相同
        self.assertGreater(sand["stress_exceed_ratio"], rock["stress_exceed_ratio"])
        self.assertIn("超过", sand["material_verdict"])
        self.assertIn("低于", rock["material_verdict"])

    def test_material_table_complete(self):
        for m in BANK_MATERIALS:
            self.assertGreater(m["tau_c"], 0)
            out = self.run_with(bank_material=m["value"])
            self.assertEqual(out["bank_tau_c_pa"], m["tau_c"])

    def test_headline_states_both_banks(self):
        out = self.run_with()
        self.assertIn("凹岸", out["headline"])
        self.assertIn("凸岸", out["headline"])


if __name__ == "__main__":
    unittest.main()

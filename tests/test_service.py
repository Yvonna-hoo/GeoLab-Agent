# -*- coding: utf-8 -*-
"""服务层与任务路由测试。

对应赛事评价里的两项：
- 「实验路由与参数校验是否正确」
- 「典型任务是否能够从自然语言输入走通到结果解释」
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geolab import service  # noqa: E402
from geolab.agent import router  # noqa: E402


class TestSweep(unittest.TestCase):
    def test_sweep_returns_series(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "sweep", "params": {},
            "sweep": {"parameter": "vegetation_cover_pct", "values": [0, 25, 50, 75, 100]},
        })
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["points"]), 5)
        self.assertTrue(all(p["ok"] for p in r["points"]))
        keys = [s["key"] for s in r["series"]]
        self.assertIn("soil_loss_t_ha_yr", keys)

    def test_sweep_curve_decreases(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "sweep", "params": {},
            "sweep": {"parameter": "vegetation_cover_pct", "values": [0, 50, 100]},
        })
        ys = [p["outputs"]["soil_loss_t_ha_yr"] for p in r["points"]]
        self.assertGreater(ys[0], ys[1])
        self.assertGreater(ys[1], ys[2])

    def test_sweep_auto_values(self):
        r = service.execute({
            "experiment": "river_bend_erosion", "mode": "sweep", "params": {},
            "sweep": {"parameter": "bend_radius_m"},
        })
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["points"]), 10)

    def test_sweep_enum_values(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "sweep", "params": {},
            "sweep": {"parameter": "practice"},
        })
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["points"]), 5)

    def test_sweep_unknown_parameter(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "sweep", "params": {},
            "sweep": {"parameter": "altitude"},
        })
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"][0]["code"], "unknown_parameter")

    def test_sweep_rejects_too_many_points(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "sweep", "params": {},
            "sweep": {"parameter": "slope_percent", "values": list(range(0, 300))},
        })
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"][0]["code"], "too_many_points")


class TestCompare(unittest.TestCase):
    def test_compare_deltas(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "compare", "params": {},
            "compare": {"variants": [
                {"label": "梯田", "params": {"practice": "terracing"}},
                {"label": "退耕", "params": {"practice": "reforestation"}},
            ]},
        })
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["rows"]), 2)
        for row in r["rows"]:
            self.assertLess(row["delta_pct"], 0)  # 措施都会减少流失

    def test_compare_empty_variants(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "compare", "params": {},
            "compare": {"variants": []},
        })
        self.assertFalse(r["ok"])

    def test_compare_partial_error_isolated(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "compare", "params": {},
            "compare": {"variants": [
                {"label": "好的", "params": {"slope_percent": 10}},
                {"label": "坏的", "params": {"slope_percent": 999}},
            ]},
        })
        self.assertTrue(r["ok"])
        self.assertTrue(r["rows"][0]["ok"])
        self.assertFalse(r["rows"][1]["ok"])


class TestAnalyze(unittest.TestCase):
    def test_sorted_by_absolute(self):
        r = service.execute({
            "experiment": "river_bend_erosion", "mode": "analyze", "params": {},
            "analyze": {"outputs": ["tau_max_pa"]},
        })
        self.assertTrue(r["ok"])
        els = [abs(e["elasticity"]) for e in r["analysis"]["elasticities"]]
        self.assertEqual(els, sorted(els, reverse=True))

    def test_velocity_elasticity_near_two(self):
        """τ ∝ v²，因此流速弹性应接近 2。"""
        r = service.execute({
            "experiment": "river_bend_erosion", "mode": "analyze", "params": {},
            "analyze": {"outputs": ["tau_max_pa"]},
        })
        vel = [e for e in r["analysis"]["elasticities"] if e["parameter"] == "mean_velocity_ms"][0]
        self.assertAlmostEqual(vel["elasticity"], 2.0, delta=0.02)


class TestRouter(unittest.TestCase):
    def test_task_a_routes_to_soil_sweep(self):
        p = router.route("在其他条件不变时，植被覆盖变化会怎样影响土壤流失估算？")
        self.assertTrue(p["ok"])
        self.assertEqual(p["experiment"], "soil_erosion_rusle")
        self.assertEqual(p["intent"], "sweep")
        self.assertEqual(p["plan"]["parameter"], "vegetation_cover_pct")

    def test_task_b_routes_to_river(self):
        p = router.route("弯曲河道的哪些部位更容易发生侵蚀或沉积？")
        self.assertTrue(p["ok"])
        self.assertEqual(p["experiment"], "river_bend_erosion")

    def test_practice_compare(self):
        p = router.route("同一块坡地，改成梯田或退耕还林之后，土壤流失量能减少多少？请做对照。")
        self.assertEqual(p["intent"], "compare")
        # 基准组由 params 的默认值承担，variants 里不再重复一次「无措施」
        self.assertEqual(len(p["plan"]["variants"]), 4)

    def test_cross_module(self):
        p = router.route("坡面产生的泥沙与河流搬运、沉积有什么联系？")
        self.assertTrue(p["ok"])
        self.assertEqual(p["intent"], "cross_module")
        self.assertIn("不应", p["explanation"])

    def test_out_of_range_precheck(self):
        p = router.route("把植被覆盖度设成 130%，看看土壤流失量是多少。")
        self.assertEqual(len(p["precheck_errors"]), 1)
        self.assertEqual(p["precheck_errors"][0]["field"], "vegetation_cover_pct")

    def test_unknown_question_asks_for_clarification(self):
        p = router.route("帮我写一首关于春天的诗。")
        self.assertFalse(p["ok"])
        self.assertIn("clarify", p)

    def test_empty_input(self):
        p = router.route("")
        self.assertFalse(p["ok"])

    def test_task_library_all_routable(self):
        for task in router.TASK_LIBRARY:
            p = router.route(task["text"])
            self.assertTrue(p["ok"], f"任务 {task['id']} 未能路由：{p}")

    def test_every_task_plan_is_executable(self):
        """任务库里的每个任务，按它的方案都应该真的能跑通。"""
        for task in router.TASK_LIBRARY:
            p = router.route(task["text"])
            payload = router.build_payload(p)
            if payload is None:          # 跨模块只做概念解释，不执行
                continue
            r = service.execute(payload)
            # 任务 G 故意越界，应当被拒绝
            if task["id"] == "G":
                self.assertFalse(r["ok"], f"任务 {task['id']} 本应被参数校验拦下")
            else:
                self.assertTrue(r["ok"], f"任务 {task['id']} 执行失败：{r.get('errors')}")


if __name__ == "__main__":
    unittest.main()

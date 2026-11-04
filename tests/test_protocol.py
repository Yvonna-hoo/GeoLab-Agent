# -*- coding: utf-8 -*-
"""协议层测试：参数校验必须结构化、可定位、可被程序消费。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geolab import service  # noqa: E402
from geolab.registry import get  # noqa: E402


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.exp = get("soil_erosion_rusle")

    def test_defaults_fill_missing(self):
        params, errors = self.exp.validate({})
        self.assertEqual(errors, [])
        self.assertEqual(params["vegetation_cover_pct"], 60.0)
        self.assertIsNone(params["cover_factor"])

    def test_out_of_range_reports_field_and_bounds(self):
        _, errors = self.exp.validate({"vegetation_cover_pct": 130})
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["field"], "vegetation_cover_pct")
        self.assertEqual(errors[0]["code"], "above_max")
        self.assertEqual(errors[0]["allowed"]["max"], 100)

    def test_below_min(self):
        _, errors = self.exp.validate({"slope_percent": -5})
        self.assertEqual(errors[0]["code"], "below_min")

    def test_unknown_parameter_rejected(self):
        _, errors = self.exp.validate({"slope_percnt": 12})
        self.assertEqual(errors[0]["code"], "unknown_parameter")
        self.assertIn("slope_percent", errors[0]["allowed"])

    def test_bad_enum(self):
        _, errors = self.exp.validate({"practice": "magic"})
        self.assertEqual(errors[0]["code"], "bad_choice")
        self.assertIn("terracing", errors[0]["allowed"])

    def test_not_a_number(self):
        _, errors = self.exp.validate({"slope_percent": "很陡"})
        self.assertEqual(errors[0]["code"], "not_a_number")

    def test_optional_blank_ok(self):
        params, errors = self.exp.validate({"cover_factor": None})
        self.assertEqual(errors, [])
        self.assertIsNone(params["cover_factor"])


class TestEnvelope(unittest.TestCase):
    def test_success_carries_assumptions(self):
        r = service.execute({"experiment": "soil_erosion_rusle", "mode": "run", "params": {}})
        self.assertTrue(r["ok"])
        self.assertGreater(len(r["assumptions"]), 2)
        self.assertGreater(len(r["limitations"]), 2)
        self.assertIn("duration_ms", r["trace"])

    def test_failure_is_structured(self):
        r = service.execute({
            "experiment": "soil_erosion_rusle", "mode": "run",
            "params": {"vegetation_cover_pct": 130},
        })
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"][0]["code"], "above_max")

    def test_unknown_experiment(self):
        r = service.execute({"experiment": "nope", "mode": "run"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"][0]["code"], "unknown_experiment")
        self.assertIn("soil_erosion_rusle", r["errors"][0]["allowed"])

    def test_unknown_mode(self):
        r = service.execute({"experiment": "soil_erosion_rusle", "mode": "explode"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"][0]["code"], "unknown_mode")


if __name__ == "__main__":
    unittest.main()

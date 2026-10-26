import math
import unittest

from scripts.plan_trade import plan_trade


class PlanTradeTests(unittest.TestCase):
    def test_risk_based_position(self):
        result = plan_trade(
            equity=100_000,
            risk_pct=0.5,
            entry=50,
            stop=47,
            target=60,
            max_position_pct=100,
        )
        self.assertEqual(result["risk_budget"], 500)
        self.assertEqual(result["risk_per_share"], 3)
        self.assertEqual(result["shares"], 166)
        self.assertEqual(result["notional"], 8300)
        self.assertEqual(result["planned_risk"], 498)
        self.assertTrue(math.isclose(result["target_r"], 10 / 3))
        self.assertEqual(result["limiting_constraint"], "account_risk")

    def test_position_cap_and_lot_size(self):
        result = plan_trade(
            equity=100_000,
            risk_pct=1,
            entry=50,
            stop=49,
            target=60,
            max_position_pct=10,
            lot_size=100,
        )
        self.assertEqual(result["position_cap_shares_before_lot"], 200)
        self.assertEqual(result["shares"], 200)
        self.assertEqual(result["notional"], 10_000)
        self.assertEqual(result["limiting_constraint"], "position_cap")
        self.assertTrue(result["warnings"])

    def test_invalid_stop_is_rejected(self):
        for stop in (50, 51):
            with self.subTest(stop=stop):
                with self.assertRaisesRegex(ValueError, "entry > stop"):
                    plan_trade(100_000, 0.5, 50, stop)

    def test_zero_share_rounding_is_explicit(self):
        result = plan_trade(
            equity=10_000,
            risk_pct=0.1,
            entry=50,
            stop=49,
            max_position_pct=20,
            lot_size=100,
        )
        self.assertEqual(result["shares"], 0)
        self.assertIn("不足一手", result["warnings"][0])

    def test_non_finite_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "有限数字"):
            plan_trade(math.inf, 0.5, 50, 47)


if __name__ == "__main__":
    unittest.main()

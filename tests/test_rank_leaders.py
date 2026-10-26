import csv
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.rank_leaders import _percentiles, rank_leaders


FIELDS = ["theme", "symbol", "date", "open", "high", "low", "close", "volume"]


def write_prices(path: Path, symbols=("LEAD", "MID", "WEAK"), periods=260) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        start = date(2025, 1, 1)
        for symbol in symbols:
            for index in range(periods):
                fraction = index / (periods - 1)
                if symbol == "LEAD":
                    close = 20 + 80 * fraction
                elif symbol == "MID":
                    close = 30 + 20 * fraction
                else:
                    close = 100 - 80 * fraction
                writer.writerow(
                    {
                        "theme": "AI",
                        "symbol": symbol,
                        "date": (start + timedelta(days=index)).isoformat(),
                        "open": close * 0.999,
                        "high": close * 1.01,
                        "low": close * 0.99,
                        "close": close,
                        "volume": 100_000,
                    }
                )


class RankLeadersTests(unittest.TestCase):
    def test_leader_ranks_first_and_weak_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            prices = Path(directory) / "prices.csv"
            write_prices(prices)
            result = rank_leaders(
                prices, "AI", min_dollar_volume=1_000_000, top=10
            )

        self.assertEqual(result["as_of"], "2025-09-17")
        self.assertEqual(result["candidates"][0]["symbol"], "LEAD")
        self.assertEqual(result["eligible_count"], 2)
        weak = next(item for item in result["excluded"] if item["symbol"] == "WEAK")
        self.assertTrue(any("50 日均线" in reason for reason in weak["reasons"]))
        self.assertIn("价格领导力候选", result["result_label"])
        self.assertTrue(result["warnings"])

    def test_metadata_is_attached_but_not_scored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prices = root / "prices.csv"
            metadata = root / "relevance.csv"
            write_prices(prices, symbols=("LEAD", "MID"))
            metadata.write_text(
                "symbol,name,relevance,note\n"
                "LEAD,强相关,90,年报证据\n"
                "MID,待核验,50,产品证据\n",
                encoding="utf-8",
            )
            with_metadata = rank_leaders(prices, "AI", metadata_path=metadata)
            without_metadata = rank_leaders(prices, "AI")

        self.assertEqual(
            with_metadata["candidates"][0]["relevance_evidence"]["relevance"], 90
        )
        self.assertEqual(
            [item["score"] for item in with_metadata["candidates"]],
            [item["score"] for item in without_metadata["candidates"]],
        )

    def test_single_candidate_has_neutral_percentiles(self):
        with tempfile.TemporaryDirectory() as directory:
            prices = Path(directory) / "prices.csv"
            write_prices(prices, symbols=("LEAD",))
            result = rank_leaders(prices, "AI")

        candidate = result["candidates"][0]
        self.assertEqual(candidate["score"], 50)
        self.assertTrue(
            all(math.isclose(value, 50) for value in candidate["component_percentiles"].values())
        )

    def test_average_rank_percentiles_handle_ties(self):
        self.assertEqual(_percentiles({"A": 1.0, "B": 2.0, "C": 2.0}), {"A": 0.0, "B": 75.0, "C": 75.0})

    def test_duplicate_symbol_date_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            prices = Path(directory) / "prices.csv"
            write_prices(prices, symbols=("LEAD",), periods=2)
            with prices.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writerow(
                    {
                        "theme": "AI",
                        "symbol": "LEAD",
                        "date": "2025-01-02",
                        "open": 20,
                        "high": 21,
                        "low": 19,
                        "close": 20,
                        "volume": 100_000,
                    }
                )
            with self.assertRaisesRegex(ValueError, "重复记录"):
                rank_leaders(prices, "AI")


if __name__ == "__main__":
    unittest.main()

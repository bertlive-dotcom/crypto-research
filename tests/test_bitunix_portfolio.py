import unittest

from bitunix.portfolio import build_portfolio_overview


class BitunixPortfolioOverviewTests(unittest.TestCase):
    def test_normalizes_spot_balances_and_locked_amounts(self):
        overview = build_portfolio_overview({
            "spot_balances": [
                {"coin": "BTC", "balance": "0.25", "balanceLocked": "0.05"},
                {"coin": "USDT", "balance": "12.5", "balanceLocked": "0"},
            ],
            "futures_account": [],
            "futures_positions": [],
        })
        self.assertEqual(overview["spot_asset_count"], 2)
        self.assertEqual(overview["spot_assets"][0], {
            "asset": "BTC", "available": "0.25", "locked": "0.05", "total": "0.30"
        })

    def test_preserves_positions_without_fabricating_fiat_valuation(self):
        position = {"symbol": "BTCUSDT", "qty": "0.01", "positionSide": "LONG"}
        overview = build_portfolio_overview({
            "spot_balances": [],
            "futures_account": [{"marginCoin": "USDT", "available": "50"}],
            "futures_positions": [position],
        })
        self.assertEqual(overview["open_futures_positions"], 1)
        self.assertEqual(overview["futures_positions"][0], position)
        self.assertIsNone(overview["fiat_valuation"])

    def test_handles_missing_or_malformed_data(self):
        overview = build_portfolio_overview({
            "spot_balances": [None, {"balance": "not-a-number"}],
            "futures_positions": None,
        })
        self.assertEqual(overview["spot_asset_count"], 0)
        self.assertEqual(overview["open_futures_positions"], 0)


if __name__ == "__main__":
    unittest.main()
